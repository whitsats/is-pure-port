@echo off
cd /d "%~dp0engine\packages\webgal"
echo Open http://127.0.0.1:4187/ in your browser.
call ..\..\node_modules\.bin\vite.cmd --config is-choice-state.vite.config.ts --host 127.0.0.1 --port 4187 --strictPort
pause
