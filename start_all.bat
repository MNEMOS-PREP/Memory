@echo off
REM ============================================================
REM  Everything.
REM
REM  Every service in scripts\services.txt, plus any sibling
REM  module repo declared in module.json `depends_on` that is
REM  checked out next to this one.
REM
REM  M04 declares NO upstreams - it is the root of the graph -
REM  so for this repo `start_all.bat` and `start_graph.bat`
REM  currently do the same thing. Both exist anyway: every repo
REM  in this platform answers to the same two commands, and the
REM  day M04 grows an optional upstream nobody has to relearn
REM  which one to type.
REM
REM  Usage:  start_all.bat          launch everything
REM          start_all.bat -Check   verify prerequisites only
REM ============================================================

cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launch.ps1" -All -Title "AI Interviewer - all services" %*
