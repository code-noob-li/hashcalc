@echo off
:: Try pythonw first (no console window)
pythonw "%~dp0hash_calc.py" 2>nul && goto :eof

:: Fallback: run python via temporary VBScript to hide window (use wscript to avoid console)
set "_vbs=%temp%\run_hidden.vbs"
> "%_vbs%" echo Set WshShell = CreateObject("WScript.Shell")
>> "%_vbs%" echo WshShell.Run "python ""%~dp0hash_calc.py""", 0, False
wscript "%_vbs%"
del "%_vbs%"
