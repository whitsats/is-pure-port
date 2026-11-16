@echo off
setlocal
cd /d "%~dp0engine\packages\webgal"
echo I's Pure HD: http://127.0.0.1:4204/
echo Close this window to stop the local server.
call ..\..\node_modules\.bin\vite.cmd --config is-v74-disc-hd.vite.config.ts --host 127.0.0.1 --port 4204 --strictPort
