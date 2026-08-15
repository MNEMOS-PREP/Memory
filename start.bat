@echo off
setlocal
cd /d "%~dp0"

REM ============================================================
REM  Dispatcher. The launchers are start_all.bat and
REM  start_graph.bat; this file stays because README.md,
REM  PORTS.txt and dependencies.txt all tell you to type
REM  `start.bat`. Renaming an entry point to tidy a directory is
REM  a bad trade.
REM
REM    start.bat            everything      -> start_all.bat
REM    start.bat graph      this module     -> start_graph.bat
REM    start.bat m04        same thing
REM    start.bat check      prerequisites, launch nothing
REM
REM  What actually runs the services: scripts\launch.ps1
REM  What you add a service to:       scripts\services.txt
REM  What closes them again:          scripts\control.ps1
REM ============================================================

if /i "%~1"=="check" goto CHECK
if /i "%~1"=="graph" goto GRAPH
if /i "%~1"=="m04"   goto GRAPH
if /i "%~1"=="all"   goto ALL
if "%~1"==""         goto ALL
goto USAGE

:ALL
call "%~dp0start_all.bat"
exit /b %errorlevel%

:GRAPH
call "%~dp0start_graph.bat"
exit /b %errorlevel%

:CHECK
call "%~dp0start_all.bat" -Check
exit /b %errorlevel%

:USAGE
echo.
echo   Unknown option "%~1".
echo.
echo     start.bat            everything
echo     start.bat graph      M04 only  ^(same as start_graph.bat^)
echo     start.bat check      verify prerequisites, launch nothing
echo.
exit /b 1
