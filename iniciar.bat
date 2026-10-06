@echo off
title PhoneCall PC
cd /d "%~dp0"
python phonecall.py
if errorlevel 1 pause
