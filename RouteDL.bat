@echo off
cd /d "%~dp0"
if exist runtime\python\pythonw.exe (
  start "" runtime\python\pythonw.exe routedl_gui.py
) else (
  start "" pythonw routedl_gui.py
)
