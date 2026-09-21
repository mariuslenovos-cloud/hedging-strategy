@echo off
REM ============================================================================
REM MISSION CONTROL - the live command center.
REM Starts a tiny local web server that regenerates the page FRESH on every
REM request (no browser caching - the documented reason serve mode exists),
REM then opens it. Read-only: reads the account, never trades.
REM
REM REQUIRES: the Pepperstone LIVE terminal (51511633) open and logged in.
REM Close this window (or Ctrl+C) to stop the server.
REM ============================================================================
cd /d "C:\Users\mariu\Downloads\hedging_strategy"
set "PY=C:\Users\mariu\AppData\Local\Programs\Python\Python311\python.exe"
start "" http://localhost:8770
"%PY%" mission_control.py --serve 8770
pause
