@echo off
REM Opens the static Chart.js dashboard (index.html) in your default browser.
REM Do NOT use http://vqtm_ran_dashboard_mar2026/ — that is not a website; you will get ERR_EMPTY_RESPONSE.
cd /d "%~dp0"
start "" "%~dp0index.html"
