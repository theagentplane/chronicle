@echo off
REM Chronicle demo + full test suite (Windows)
cd /d "%~dp0.."
python scripts\run.py quickrun %*
