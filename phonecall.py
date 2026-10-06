#!/usr/bin/env python3
import ctypes
import ctypes.wintypes as wt
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import ttk

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
ADB_CANDIDATES = [
    r"C:\adb\adb.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"),
    r"C:\Program Files\platform-tools\adb.exe",
    "adb",
]
ROW_SPLIT = re.compile(r", (\w+)=")

BG = "#0E1319"
PANEL = "#151C25"
PANEL2 = "#1B2430"
HOVER = "#242F3D"
BORDER = "#27313F"
TEXT = "#E9EEF5"
MUTED = "#8896A8"
DIM = "#5C6B7F"
ACCENT = "#3B82F6"
GREEN = "#22C55E"
GREEN_D = "#16A34A"
RED = "#EF4444"
RED_D = "#DC2626"
AMBER = "#F59E0B"
OFF_BG = "#1B2430"
OFF_FG = "#55637A"

KEY_LETTERS = {
    "2": "ABC", "3": "DEF", "4": "GHI", "5": "JKL", "6": "MNO",
    "7": "PQRS", "8": "TUV", "9": "WXYZ", "0": "+",
}
WIN_W = 760
WIN_H = 930


def find_adb():
    for c in ADB_CANDIDATES:
        if c == "adb" or os.path.isfile(c):
            return c
    return "adb"


def mkbtn(parent, text, *, bg, fg="white", hover=None, command=None,
          font=("Segoe UI", 10), padx=14, pady=7, takefocus=0):
    b = tk.Button(parent, text=text, font=font, bg=bg, fg=fg,
                  activebackground=hover or bg, activeforeground=fg,
                  relief="flat", bd=0, highlightthickness=0, takefocus=takefocus,
                  cursor="hand2", command=command, padx=padx, pady=pady)
    b.base_bg = bg
    b.base_hover = hover or bg
    if hover:
        b.bind("<Enter>", lambda e: b.config(bg=b.base_hover)
               if str(b.cget("state")) == "normal" else None)
        b.bind("<Leave>", lambda e: b.config(bg=b.base_bg))
    return b


def btn_on(b, color, hover):
    b.base_bg = color
    b.base_hover = hover
    b.config(state="normal", bg=color, fg="white",
             activebackground=hover, activeforeground="white")


def btn_off(b):
    b.base_bg = OFF_BG
    b.base_hover = OFF_BG
    b.config(state="disabled", bg=OFF_BG, fg=OFF_FG,
             activebackground=OFF_BG, activeforeground=OFF_FG)


class Adb:
    def __init__(self):
        self.exe = find_adb()
        self.port = None
        self.serial = None
        self.model = None

    def run(self, args, timeout=25, raw=False):
        base = [self.exe]
        if self.port:
            base += ["-P", str(self.port)]
        try:
            p = subprocess.run(
                base + args, capture_output=True, timeout=timeout,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except subprocess.TimeoutExpired:
            return None, "timeout"
        out = p.stdout.decode("utf-8", "replace")
        err = p.stderr.decode("utf-8", "replace")
        if raw:
            return out, err
        return out, (err if p.returncode else "")

    def pick_port(self):
        for port in (5037, 5038, 5039):
            self.port = port
            out, _ = self.run(["get-state"], timeout=6)
            if out and "device" in out:
                return True
        self.port = 5038
        self.run(["start-server"], timeout=15)
        return True

    def ensure_device(self):
        out, _ = self.run(["devices"], timeout=15)
        lines = [l for l in (out or "").splitlines()[1:] if l.strip()]
        for l in lines:
            if "\tdevice" in l:
                self.serial = l.split()[0]
                self.model = self._model()
                return True
        for l in lines:
            if "\tunauthorized" in l:
                return "unauthorized"
        self.run(["mdns", "services"], timeout=8)
        out, _ = self.run(["mdns", "services"], timeout=8)
        for l in (out or "").splitlines():
            if "_adb-tls-connect._tcp" in l and " " in l:
                addr = l.split()[-1]
                self.run(["connect", addr], timeout=12)
        out, _ = self.run(["devices"], timeout=15)
        for l in (out or "").splitlines()[1:]:
            if "\tdevice" in l:
                self.serial = l.split()[0]
                self.model = self._model()
                return True
        return False

    def _model(self):
        out, _ = self.run(["shell", "getprop", "ro.product.model"], timeout=10)
        return (out or "").strip()

    def shell(self, *cmd, timeout=25):
        return self.run(["shell"] + list(cmd), timeout=timeout)

    def call_state(self):
        out, _ = self.shell("dumpsys", "telephony.registry", timeout=20)
        states = [int(s) for s in re.findall(r"mCallState=(\d)", out or "")]
        if not states:
            return 0, ""
        inc = re.search(r"mCallIncomingNumber=(\S*)", out or "")
        return max(states), (inc.group(1) if inc else "")

    def dial(self, number):
        n = sanitize(number)
        if not n:
            return False, "Número vacío"
        out, err = self.shell(
            "am", "start", "-a", "android.intent.action.CALL", "-d", "tel:" + n
        )
        if out and "Error" in out:
            return False, out.strip()
        if err and "Error" in err:
            return False, err.strip()
        return True, ""

    def hangup(self):
        self.shell("input", "keyevent", "KEYCODE_ENDCALL")
        return True, ""

    def answer(self):
        for key in ("KEYCODE_HEADSETHOOK", "KEYCODE_CALL"):
            self.shell("input", "keyevent", key)
            time.sleep(0.4)
            st, _ = self.call_state()
            if st == 2:
                return True, ""
        return False, "No se pudo contestar"

    def contacts(self, q=""):
        out, _ = self.shell(
            "content", "query", "--uri",
            "content://com.android.contacts/data/phones",
            "--projection", "display_name:data1", timeout=40,
        )
        rows = parse_rows(out or "")
        items = [(clean(r.get("display_name", "")), clean(r.get("data1", "")))
                 for r in rows]
        items = [(n, v) for n, v in items if v]
        if q:
            ql = q.lower()
            items = [i for i in items if ql in i[0].lower() or ql in i[1]]
        items.sort(key=lambda x: x[0].lower())
        return items

    def calllog(self):
        out, _ = self.shell(
            "content", "query", "--uri", "content://call_log/calls",
            "--projection", "number:name:date:duration:type", timeout=40,
        )
        rows = parse_rows(out or "")
        result = []
        for r in rows:
            try:
                ts = datetime.fromtimestamp(int(r.get("date", "0")) / 1000)
            except Exception:
                ts = None
            try:
                dur = int(r.get("duration", "0"))
            except Exception:
                dur = 0
            result.append({
                "when": ts,
                "name": clean(r.get("name", "")),
                "number": clean(r.get("number", "")),
                "duration": dur,
                "type": int(r.get("type", "0") or 0),
            })
        result.sort(key=lambda x: x["when"].timestamp() if x["when"] else 0, reverse=True)
        return result


def sanitize(number):
    return re.sub(r"[^\d+*#]", "", number or "")


def clean(v):
    v = (v or "").strip()
    return "" if v.upper() == "NULL" else v


def parse_rows(text):
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("Row:"):
            continue
        line = re.sub(r"^Row: \d+ ", "", line)
        parts = ROW_SPLIT.split(line)
        d = {parts[0].split("=", 1)[0]: parts[0].split("=", 1)[1]} if "=" in parts[0] else {}
        for i in range(1, len(parts) - 1, 2):
            d[parts[i]] = parts[i + 1]
        rows.append(d)
    return rows


def make_icon(size=64):
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return None
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([1, 1, size - 2, size - 2], radius=size // 4,
                        fill=(59, 130, 246, 255))
    glyph = "\U0001F4DE"
    for font_name, fallback in (("seguiemj.ttf", "seguisym.ttf"),):
        try:
            f = ImageFont.truetype(font_name, int(size * 0.52))
            d.text((size // 2, size // 2 - size // 16), glyph, font=f,
                   fill="white", anchor="mm")
            return img
        except Exception:
            try:
                f = ImageFont.truetype(fallback, int(size * 0.5))
                d.text((size // 2, size // 2), "\u260e", font=f,
                       fill="white", anchor="mm")
                return img
            except Exception:
                break
    d.ellipse([size * 0.28, size * 0.28, size * 0.72, size * 0.72],
              outline="white", width=max(2, size // 12))
    return img


class Tray(threading.Thread):
    def __init__(self, app):
        super().__init__(daemon=True)
        self.app = app
        self.icon = None

    def run(self):
        try:
            import pystray
        except Exception:
            return
        img = make_icon(64)
        if img is None:
            return
        menu = pystray.Menu(
            pystray.MenuItem("Abrir PhoneCall", lambda: self.app.post("show"), default=True),
            pystray.MenuItem("Salir", lambda: self.app.post("quit")),
        )
        self.icon = pystray.Icon("phonecall", img, "PhoneCall PC", menu)
        self.icon.run()


class Hotkey(threading.Thread):
    def __init__(self, app):
        super().__init__(daemon=True)
        self.app = app

    def run(self):
        user32 = ctypes.windll.user32
        MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x0001, 0x0002, 0x4000
        WM_HOTKEY = 0x0312
        if not user32.RegisterHotKey(None, 1, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, ord("S")):
            return
        msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                self.app.post("toggle")
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        user32.UnregisterHotKey(None, 1)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PhoneCall PC")
        self.geometry(f"{WIN_W}x{WIN_H}")
        self.minsize(620, 780)
        self.configure(bg=BG)
        self.adb = Adb()
        self.q = queue.Queue()
        self.cur_state = 0
        self.call_start = None
        self.tab = "contacts"
        self._contacts_cache = None
        self.protocol("WM_DELETE_WINDOW", self.hide)
        self._load_cfg()
        self._build()
        self._center()
        self.ent.focus_set()
        self.after(250, self._center)
        self.after(120, self._dark_chrome)
        self.after(80, self._poll_queue)
        threading.Thread(target=self._init_device, daemon=True).start()
        self._tick()
        Hotkey(self).start()
        self.tray = Tray(self)
        self.tray.start()

    def _dark_chrome(self):
        try:
            hwnd = self.winfo_id()
            GA_ROOT = 2
            root = ctypes.windll.user32.GetAncestor(hwnd, GA_ROOT)
            if root:
                hwnd = root
            val = ctypes.c_int(1)
            for attr in (20, 19):
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(val), ctypes.sizeof(val))
        except Exception:
            pass

    def _center(self):
        u = ctypes.windll.user32
        wa = wt.RECT()
        u.SystemParametersInfoW(0x0030, 0, ctypes.byref(wa), 0)
        ww, wh = wa.right - wa.left, wa.bottom - wa.top
        h = WIN_H
        self.geometry(f"{WIN_W}x{h}+{wa.left}+{wa.top}")
        self.update_idletasks()
        hwnd = u.GetAncestor(self.winfo_id(), 2) or self.winfo_id()
        r = wt.RECT()
        u.GetWindowRect(hwnd, ctypes.byref(r))
        ow, oh = r.right - r.left, r.bottom - r.top
        if not ow or not oh:
            ow, oh = WIN_W + 22, h + 56
        if oh > wh - 8:
            h = max(780, h - (oh - (wh - 8)))
            self.geometry(f"{WIN_W}x{h}")
            self.update_idletasks()
            u.GetWindowRect(hwnd, ctypes.byref(r))
            ow, oh = r.right - r.left, r.bottom - r.top
        x = wa.left + max(0, (ww - ow) // 2)
        y = wa.top + max(0, (wh - oh) // 2)
        self.geometry(f"{WIN_W}x{h}+{x}+{y}")
        self.update_idletasks()

    def _load_cfg(self):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                self.cfg = json.load(f)
        except Exception:
            self.cfg = {}

    def _save_cfg(self):
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.cfg, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def post(self, item):
        self.q.put(item)

    def _poll_queue(self):
        try:
            while True:
                item = self.q.get_nowait()
                if item == "toggle":
                    self.toggle()
                elif item == "quit":
                    self.destroy()
                elif item == "show":
                    self.deiconify()
                    self.lift()
                    self.focus_force()
                elif isinstance(item, tuple) and item[0] == "contacts":
                    self._fill_contacts(item[1])
                elif isinstance(item, tuple) and item[0] == "log":
                    self._fill_log(item[1])
                elif isinstance(item, tuple) and item[0] == "conn":
                    self.set_conn(item[1], item[2])
                elif isinstance(item, tuple) and item[0] == "err":
                    self.set_status(item[1])
        except queue.Empty:
            pass
        self.after(80, self._poll_queue)

    def _styles(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("Treeview", background=PANEL2, fieldbackground=PANEL2,
                    foreground=TEXT, rowheight=30, font=("Segoe UI", 10),
                    borderwidth=0, relief="flat")
        s.configure("Treeview.Heading", background=PANEL, foreground=MUTED,
                    font=("Segoe UI", 9, "bold"), relief="flat", padding=(8, 7))
        s.map("Treeview.Heading",
              background=[("active", PANEL2)],
              foreground=[("active", TEXT)])
        s.map("Treeview",
              background=[("selected", ACCENT)],
              foreground=[("selected", "white")])
        s.configure("Treeview.odd", background=PANEL2)
        s.configure("Treeview.even", background="#18202A")
        s.configure("Treeview.missed", foreground="#F87171")
        s.configure("Vertical.TScrollbar", background=BORDER, troughcolor=PANEL,
                    bordercolor=PANEL, arrowcolor=DIM, relief="flat", width=10)
        s.map("Vertical.TScrollbar",
              background=[("active", DIM)], arrowcolor=[("active", TEXT)])

    def _build(self):
        self._styles()

        bar = tk.Frame(self, bg=ACCENT, height=3)
        bar.pack(fill="x")
        bar.pack_propagate(False)

        head = tk.Frame(self, bg=BG)
        head.pack(fill="x", padx=18, pady=(14, 12))
        tl = tk.Frame(head, bg=BG)
        tl.pack(side="left")
        tk.Label(tl, text="PhoneCall", font=("Segoe UI", 17, "bold"),
                 bg=BG, fg=TEXT).pack(side="left")
        tk.Label(tl, text="  PC", font=("Segoe UI", 11, "bold"),
                 bg=BG, fg=ACCENT).pack(side="left", padx=(4, 0))
        tk.Label(tl, text="   marcador remoto", font=("Segoe UI", 9),
                 bg=BG, fg=DIM).pack(side="left", padx=(8, 0))

        self.conn_pill = tk.Frame(head, bg="#0F2A1B",
                                  highlightbackground="#215C39",
                                  highlightthickness=1)
        self.conn_pill.pack(side="right")
        self.conn_dot = tk.Label(self.conn_pill, text="●", font=("Segoe UI", 8),
                                 bg="#0F2A1B", fg=AMBER)
        self.conn_dot.pack(side="left", padx=(10, 4), pady=5)
        self.conn_lbl = tk.Label(self.conn_pill, text="conectando…",
                                 font=("Segoe UI", 9), bg="#0F2A1B", fg=AMBER)
        self.conn_lbl.pack(side="left", padx=(0, 10), pady=5)

        lbl = tk.Frame(self, bg=BG)
        lbl.pack(fill="x", padx=18)
        tk.Label(lbl, text="NÚMERO", font=("Segoe UI", 8, "bold"),
                 bg=BG, fg=DIM).pack(anchor="w")

        disp = tk.Frame(self, bg=PANEL2, highlightbackground=BORDER,
                        highlightthickness=1)
        disp.pack(fill="x", padx=18, pady=(5, 12))
        self.num_var = tk.StringVar()
        ent = tk.Entry(disp, textvariable=self.num_var, font=("Segoe UI", 24),
                       bg=PANEL2, fg=TEXT, insertbackground=ACCENT,
                       relief="flat", bd=0, justify="center",
                       highlightthickness=0)
        ent.pack(fill="x", ipady=12, padx=2)
        ent.bind("<Return>", lambda e: self.do_call())
        self.ent = ent

        mid = tk.Frame(self, bg=BG)
        mid.pack(fill="both", expand=True, padx=18)

        kp = tk.Frame(mid, bg=BG)
        kp.pack(side="left", fill="y")
        keys = [("1", ""), ("2", ""), ("3", ""), ("4", ""), ("5", ""), ("6", ""),
                ("7", ""), ("8", ""), ("9", ""), ("*", ""), ("0", ""), ("#", "")]
        for i, (dig, _) in enumerate(keys):
            r, c = divmod(i, 3)
            k = tk.Frame(kp, bg=PANEL2, highlightbackground=BORDER,
                         highlightthickness=1, cursor="hand2")
            k.grid(row=r, column=c, padx=4, pady=4, sticky="nsew")
            sub = KEY_LETTERS.get(dig, "")
            tk.Label(k, text=dig, font=("Segoe UI", 20, "bold"), bg=PANEL2,
                     fg=TEXT).place(relx=0.5, rely=0.40 if sub else 0.5,
                                    anchor="center")
            if sub:
                tk.Label(k, text=sub, font=("Segoe UI", 7, "bold"), bg=PANEL2,
                         fg=DIM).place(relx=0.5, rely=0.74, anchor="center")
            k.bind("<Button-1>", lambda e, d=dig: self._key(d))
            for ch in k.winfo_children():
                ch.bind("<Button-1>", lambda e, d=dig: self._key(d))
            k.bind("<Enter>", lambda e, w=k: w.config(bg=HOVER)
                   or [x.config(bg=HOVER) for x in w.winfo_children()])
            k.bind("<Leave>", lambda e, w=k: w.config(bg=PANEL2)
                   or [x.config(bg=PANEL2) for x in w.winfo_children()])
        for c in range(3):
            kp.grid_columnconfigure(c, weight=1, minsize=110)
        for r in range(4):
            kp.grid_rowconfigure(r, weight=1, minsize=62)

        rc = tk.Frame(mid, bg=BG)
        rc.pack(side="left", fill="both", expand=True, padx=(14, 0))
        self.call_btn = mkbtn(rc, "  Llamar", bg=GREEN_D, hover=GREEN,
                              font=("Segoe UI", 13, "bold"),
                              command=self.do_call, pady=13)
        self.call_btn.pack(fill="x")

        rr = tk.Frame(rc, bg=BG)
        rr.pack(fill="x", pady=(8, 0))
        rr.grid_columnconfigure(0, weight=1)
        rr.grid_columnconfigure(1, weight=1)
        b_clr = mkbtn(rr, "Borrar", bg=PANEL2, fg=MUTED, hover=HOVER,
                      font=("Segoe UI", 10), command=self._clear, pady=9)
        b_clr.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        b_plus = mkbtn(rr, "+", bg=PANEL2, fg=MUTED, hover=HOVER,
                       font=("Segoe UI", 11, "bold"), command=lambda: self._key("+"),
                       pady=9)
        b_plus.grid(row=0, column=1, sticky="nsew", padx=(4, 0))

        tbar = tk.Frame(rc, bg=BG)
        tbar.pack(fill="x", pady=(16, 0))
        self.tab_btns = {}
        for key, text in (("contacts", "  Contactos  "), ("log", "  Historial  ")):
            b = mkbtn(tbar, text, bg=PANEL, fg=MUTED, hover=HOVER,
                      font=("Segoe UI", 10, "bold"),
                      command=lambda k=key: self._show_tab(k), pady=8)
            b.pack(side="left")
            self.tab_btns[key] = b
        self.tab_btns["contacts"].config(bg=ACCENT, fg="white")

        body = tk.Frame(rc, bg=PANEL, highlightbackground=BORDER,
                        highlightthickness=1)
        body.pack(fill="both", expand=True, pady=(8, 0))

        act = tk.Frame(self, bg=PANEL, highlightbackground=BORDER,
                       highlightthickness=1)
        act.pack(fill="x", padx=18, pady=(14, 12))
        left = tk.Frame(act, bg=PANEL)
        left.pack(side="left", padx=14, pady=11)
        self.dot = tk.Label(left, text="●", font=("Segoe UI", 11), bg=PANEL, fg=DIM)
        self.dot.pack(side="left")
        self.state_lbl = tk.Label(left, text="En espera", font=("Segoe UI", 11, "bold"),
                                  bg=PANEL, fg=MUTED)
        self.state_lbl.pack(side="left", padx=(7, 0))
        self.timer_lbl = tk.Label(left, text="", font=("Segoe UI", 11),
                                  bg=PANEL, fg=DIM)
        self.timer_lbl.pack(side="left", padx=(10, 0))

        rb = tk.Frame(act, bg=PANEL)
        rb.pack(side="right", padx=12, pady=9)
        self.b_answer = mkbtn(rb, "Contestar", bg=ACCENT, hover="#5B9BF8",
                              command=self.do_answer, font=("Segoe UI", 10))
        self.b_hang = mkbtn(rb, "Colgar", bg=RED_D, hover=RED,
                            command=self.do_hang, font=("Segoe UI", 10))
        self.b_rej = mkbtn(rb, "Rechazar", bg="#374151", hover="#4B5563",
                           command=self.do_hang, font=("Segoe UI", 10))
        self.b_answer.pack(side="left", padx=3)
        self.b_hang.pack(side="left", padx=3)
        self.b_rej.pack(side="left", padx=3)
        for b in (self.b_answer, self.b_hang, self.b_rej):
            btn_off(b)

        self.p1 = tk.Frame(body, bg=PANEL)
        self.p2 = tk.Frame(body, bg=PANEL)

        sbar = tk.Frame(self.p1, bg=PANEL)
        sbar.pack(fill="x", padx=10, pady=(10, 8))
        self.q_var = tk.StringVar()
        self.ph_on = False
        self.q_entry = tk.Entry(sbar, textvariable=self.q_var,
                                font=("Segoe UI", 11), bg=PANEL2, fg=MUTED,
                                insertbackground=TEXT, relief="flat", bd=0,
                                highlightbackground=BORDER, highlightthickness=1,
                                highlightcolor=ACCENT)
        self.q_entry.pack(side="left", fill="x", expand=True, ipady=7, padx=(0, 8))
        self.q_entry.insert(0, "Buscar contacto…")
        self.ph_on = True
        self.q_entry.bind("<FocusIn>", self._ph_in)
        self.q_entry.bind("<FocusOut>", self._ph_out)
        self.q_entry.bind("<KeyRelease>", lambda ev: self.search_contacts())
        mkbtn(sbar, "Actualizar", bg=PANEL2, fg=MUTED, hover=HOVER,
              font=("Segoe UI", 9), command=lambda: self.load_contacts(True),
              pady=7).pack(side="left")

        wrap1 = tk.Frame(self.p1, bg=PANEL)
        wrap1.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.t_contacts = ttk.Treeview(wrap1, columns=("name", "number"),
                                       show="headings", selectmode="browse",
                                       height=6)
        self.t_contacts.heading("name", text="NOMBRE")
        self.t_contacts.heading("number", text="NÚMERO")
        self.t_contacts.column("name", width=200, anchor="w", stretch=True)
        self.t_contacts.column("number", width=130, anchor="w", stretch=True)
        sb = ttk.Scrollbar(wrap1, orient="vertical", command=self.t_contacts.yview)
        self.t_contacts.configure(yscrollcommand=sb.set)
        self.t_contacts.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.t_contacts.bind("<ButtonRelease-1>", self._sel_contact)
        self.t_contacts.bind("<Double-1>", self._pick_contact)

        sbar2 = tk.Frame(self.p2, bg=PANEL)
        sbar2.pack(fill="x", padx=10, pady=(10, 8))
        tk.Label(sbar2, text="Registro de llamadas del celular", bg=PANEL,
                 fg=MUTED, font=("Segoe UI", 10)).pack(side="left")
        mkbtn(sbar2, "Actualizar", bg=PANEL2, fg=MUTED, hover=HOVER,
              font=("Segoe UI", 9), command=self.load_log, pady=7).pack(side="right")

        wrap2 = tk.Frame(self.p2, bg=PANEL)
        wrap2.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        cols2 = ("when", "name", "number", "type", "dur")
        self.t_log = ttk.Treeview(wrap2, columns=cols2, show="headings",
                                  selectmode="browse", height=6)
        for cid, txt, w in (("when", "FECHA", 95), ("name", "NOMBRE", 100),
                            ("number", "NÚMERO", 95), ("type", "TIPO", 65),
                            ("dur", "DUR.", 55)):
            self.t_log.heading(cid, text=txt)
            self.t_log.column(cid, width=w, anchor="w", stretch=True)
        sb2 = ttk.Scrollbar(wrap2, orient="vertical", command=self.t_log.yview)
        self.t_log.configure(yscrollcommand=sb2.set)
        self.t_log.pack(side="left", fill="both", expand=True)
        sb2.pack(side="right", fill="y")
        self.t_log.bind("<ButtonRelease-1>", self._sel_log)
        self.t_log.bind("<Double-1>", self._pick_log)
        self._show_tab("contacts")

        foot = tk.Frame(self, bg=BG)
        foot.pack(fill="x", padx=18, pady=(10, 12))
        self.status = tk.Label(foot, text="Listo", bg=BG, fg=MUTED,
                               font=("Segoe UI", 9), anchor="w")
        self.status.pack(side="left", fill="x", expand=True)
        tk.Label(foot, text="Ctrl+Alt+S  mostrar / ocultar", bg=BG, fg=DIM,
                 font=("Segoe UI", 8)).pack(side="right")

    def _key(self, d):
        self.num_var.set(self.num_var.get() + d)

    def _clear(self):
        v = self.num_var.get()
        self.num_var.set(v[:-1])

    def _ph_in(self, _e):
        if self.ph_on:
            self.q_entry.delete(0, "end")
            self.q_entry.config(fg=TEXT)
            self.ph_on = False

    def _ph_out(self, _e):
        if not self.q_var.get().strip():
            self.q_entry.delete(0, "end")
            self.q_entry.insert(0, "Buscar contacto…")
            self.q_entry.config(fg=MUTED)
            self.ph_on = True

    def _query_text(self):
        return "" if self.ph_on else self.q_var.get().strip()

    def _show_tab(self, name):
        self.tab = name
        for k, b in self.tab_btns.items():
            if k == name:
                b.config(bg=ACCENT, fg="white")
            else:
                b.config(bg=PANEL, fg=MUTED)
        if name == "contacts":
            self.p2.pack_forget()
            self.p1.pack(fill="both", expand=True)
        else:
            self.p1.pack_forget()
            self.p2.pack(fill="both", expand=True)

    def set_conn(self, text, state):
        conf = {
            "ok": ("#0F2A1B", "#215C39", GREEN, GREEN),
            "wait": ("#2A2110", "#5C4A1E", AMBER, AMBER),
            "err": ("#2B1315", "#5C2226", RED, RED),
        }[state]
        bg, bd, dot, fg = conf
        self.conn_pill.config(bg=bg, highlightbackground=bd)
        self.conn_dot.config(bg=bg, fg=dot)
        self.conn_lbl.config(bg=bg, fg=fg, text=text)

    def set_status(self, txt):
        self.status.config(text=txt)

    def _init_device(self):
        self.post(("conn", "conectando…", "wait"))
        self.adb.pick_port()
        r = self.adb.ensure_device()
        if r is True:
            model = self.adb.model or self.adb.serial or "celular"
            self.post(("conn", f"  {model}", "ok"))
            self.post(("err", f"Conectado · puerto adb {self.adb.port}"))
            self.load_contacts()
            self.load_log()
        elif r == "unauthorized":
            self.post(("conn", "no autorizado", "err"))
            self.post(("err", "Acepta la depuración en el celular"))
        else:
            self.post(("conn", "sin celular", "err"))
            self.post(("err", "Revisa la depuración inalámbrica del celular"))

    def load_contacts(self, refresh=False):
        if not refresh and self._contacts_cache is not None:
            self._apply_query(self._query_text())
            return
        self.set_status("Cargando contactos…")
        threading.Thread(target=self._contacts_worker, daemon=True).start()

    def _contacts_worker(self):
        try:
            items = self.adb.contacts()
            self.post(("contacts", items))
        except Exception as e:
            self.post(("err", f"Error contactos: {e}"))

    @staticmethod
    def _filter(items, q):
        if not q:
            return items
        ql = q.lower()
        return [i for i in items if ql in i[0].lower() or ql in i[1]]

    def _apply_query(self, q):
        if self._contacts_cache is None:
            self.load_contacts()
            return
        items = self._filter(self._contacts_cache, q)
        self._fill_view(items)
        self.set_status(f"{len(items)} contactos" + (f' · "{q}"' if q else ""))

    def _fill_view(self, items):
        self.t_contacts.delete(*self.t_contacts.get_children())
        for i, (name, num) in enumerate(items):
            self.t_contacts.insert("", "end", values=(name, num),
                                   tags=("even" if i % 2 else "odd",))

    def _fill_contacts(self, items):
        self._contacts_cache = items
        self._apply_query(self._query_text())

    def search_contacts(self, _e=None):
        if self.ph_on:
            if str(self.focus_get()) == str(self.q_entry):
                self.q_entry.delete(0, "end")
                self.q_entry.config(fg=TEXT)
                self.ph_on = False
            else:
                return
        if not self.q_var.get().strip():
            self._apply_query("")
            return
        if hasattr(self, "_s_after"):
            try:
                self.after_cancel(self._s_after)
            except Exception:
                pass
        self._s_after = self.after(200, lambda: self._apply_query(
            "" if self.ph_on else self.q_var.get().strip()))

    def load_log(self):
        self.set_status("Cargando historial…")
        threading.Thread(target=self._log_worker, daemon=True).start()

    def _log_worker(self):
        try:
            self.post(("log", self.adb.calllog()))
        except Exception as e:
            self.post(("err", f"Error historial: {e}"))

    TYPE_MAP = {1: "Entrante", 2: "Saliente", 3: "Perdida",
                4: "Rechazada", 5: "Bloqueada"}

    def _fill_log(self, rows):
        self.t_log.delete(*self.t_log.get_children())
        for i, r in enumerate(rows):
            when = r["when"].strftime("%d/%m/%y  %H:%M") if r["when"] else ""
            m, s = divmod(r["duration"], 60)
            dur = f"{m}:{s:02d}" if r["duration"] else "—"
            tags = ["even" if i % 2 else "odd"]
            if r["type"] in (3, 4, 5):
                tags.append("missed")
            self.t_log.insert("", "end", values=(
                when, r["name"] or r["number"], r["number"],
                self.TYPE_MAP.get(r["type"], "—"), dur), tags=tuple(tags))
        self.set_status(f"{len(rows)} llamadas en historial")

    def _sel_contact(self, _e):
        sel = self.t_contacts.selection()
        if not sel:
            return
        num = self.t_contacts.item(sel[0])["values"][1]
        self.num_var.set(str(num))

    def _pick_contact(self, _e):
        self.do_call()

    def _sel_log(self, _e):
        sel = self.t_log.selection()
        if not sel:
            return
        num = self.t_log.item(sel[0])["values"][2]
        self.num_var.set(str(num))

    def _pick_log(self, _e):
        self._sel_log(_e)

    def do_call(self):
        num = self.num_var.get().strip()
        if not num:
            self.set_status("Escribe un número o elige un contacto")
            return
        self.set_status(f"Llamando a {num} …")
        threading.Thread(target=self._call_worker, args=(num,), daemon=True).start()

    def _call_worker(self, num):
        ok, err = self.adb.dial(num)
        if ok:
            self.cfg["last"] = num
            self._save_cfg()
            self.post(("err", f"Llamando a {num}"))
        else:
            self.post(("err", f"Error al llamar: {err}"))

    def do_hang(self):
        threading.Thread(target=self._hang_worker, daemon=True).start()

    def _hang_worker(self):
        self.adb.hangup()
        self.post(("err", "Llamada finalizada"))

    def do_answer(self):
        self.set_status("Contestando…")
        threading.Thread(target=self._ans_worker, daemon=True).start()

    def _ans_worker(self):
        ok, err = self.adb.answer()
        self.post(("err", "Llamada contestada" if ok else err))

    def _tick(self):
        threading.Thread(target=self._state_worker, daemon=True).start()
        self.after(1200, self._tick)

    def _state_worker(self):
        try:
            st, inc = self.adb.call_state()
        except Exception:
            st, inc = self.cur_state, ""
        self.after(0, lambda: self._apply_state(st, inc))

    def _apply_state(self, st, inc):
        if st != self.cur_state:
            if st == 2 and self.cur_state != 2:
                self.call_start = time.time()
            elif st == 0:
                self.call_start = None
            self.cur_state = st
        if st == 1:
            who = f"  {inc}" if inc else ""
            self.dot.config(fg=AMBER)
            self.state_lbl.config(text="Llamada entrante" + who, fg=AMBER)
            self.timer_lbl.config(text="")
            btn_on(self.b_answer, ACCENT, "#5B9BF8")
            btn_on(self.b_hang, RED_D, RED)
            btn_on(self.b_rej, "#374151", "#4B5563")
        elif st == 2:
            t = ""
            if self.call_start:
                d = int(time.time() - self.call_start)
                t = f"{d // 60:02d}:{d % 60:02d}"
            self.dot.config(fg=GREEN)
            self.state_lbl.config(text="En llamada", fg=GREEN)
            self.timer_lbl.config(text=t, fg=GREEN)
            btn_off(self.b_answer)
            btn_on(self.b_hang, RED_D, RED)
            btn_off(self.b_rej)
        else:
            self.dot.config(fg=DIM)
            self.state_lbl.config(text="En espera", fg=MUTED)
            self.timer_lbl.config(text="")
            btn_off(self.b_answer)
            btn_off(self.b_hang)
            btn_off(self.b_rej)

    def toggle(self):
        if self.state() == "withdrawn":
            self.deiconify()
            self.lift()
            self.focus_force()
        else:
            self.withdraw()

    def hide(self):
        self.withdraw()
        self.set_status("Minimizado · Ctrl+Alt+S para abrir")


def main():
    if os.name == "nt":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:
                pass
    img = make_icon(32)
    app = App()
    if img is not None:
        try:
            from PIL import ImageTk
            app.iconphoto(True, ImageTk.PhotoImage(img))
        except Exception:
            pass
    last = app.cfg.get("last")
    if last:
        app.num_var.set(last)
    app.mainloop()


if __name__ == "__main__":
    main()
