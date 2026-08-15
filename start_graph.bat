@echo off
REM ============================================================
REM  M04 alone:  API 8104.
REM
REM  One Windows Terminal window, one tab per service, control
REM  tab last. The control tab owns shutdown and kills by PID -
REM  never by window title (see scripts\launch.ps1 for why).
REM ============================================================

cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launch.ps1" -Only m04 -Title "M04 - Skill Graph & MNEMOS Memory" %*
