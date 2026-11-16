@echo off
cd /d "%~dp0engine\packages\webgal"
echo Open http://127.0.0.1:4178/ in your browser.
call ..\..\node_modules\.bin\vite.cmd --config is-sample.vite.config.ts --host 127.0.0.1 --port 4178 --strictPort
pause
