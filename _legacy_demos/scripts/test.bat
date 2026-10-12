@echo off
REM Chronicle full test suite (Windows)
cd /d "%~dp0.."
python scripts\run.py test %*
