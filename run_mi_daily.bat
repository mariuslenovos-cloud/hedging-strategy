@echo off
REM Daily GridStat live-intelligence run (scheduled). Requires the Pepperstone
REM live terminal (51511633) to be running for the MT5 API to connect.
cd /d "C:\Users\mariu\Downloads\hedging_strategy"
set "PY=C:\Users\mariu\AppData\Local\Programs\Python\Python311\python.exe"
set "LOG=analysis_data\mi_daily.log"
echo.>> "%LOG%"
echo =====================================================>> "%LOG%"
echo RUN %date% %time%>> "%LOG%"
echo =====================================================>> "%LOG%"
REM 0) version the live gate DBs (rollback point; content-hashed, no dupes)
"%PY%" gridstat_db_version.py snapshot>> "%LOG%" 2>&1
REM 1) refresh the live scorecard/dashboard (reliable: real account deals)
"%PY%" gridstat_dashboard.py --once>> "%LOG%" 2>&1
REM 2) mine live per-fingerprint performance (reliable: EA's real fingerprints + outcomes)
"%PY%" gridstat_fingerprint_mi.py>> "%LOG%" 2>&1
REM 3) reproduction refresh = coarse HEADS-UP only (parity-approximate; confirm via EA-shadow before acting)
"%PY%" gridstat_shadow_refresh.py>> "%LOG%" 2>&1
REM 4) the REGISTER = single management view (status+action per fingerprint) + rolling history
"%PY%" gridstat_fingerprint_register.py>> "%LOG%" 2>&1
REM 5) MISSION CONTROL = regenerate the live command center HTML
"%PY%" mission_control.py>> "%LOG%" 2>&1
