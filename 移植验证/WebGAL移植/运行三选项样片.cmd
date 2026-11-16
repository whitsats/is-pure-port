@echo off
setlocal
cd /d "%~dp0engine\packages\webgal"
echo I's Pure prototype: http://127.0.0.1:4192/
echo Close this window to stop the local server.
call ..\..\node_modules\.bin\vite.cmd --config is-threechoices.vite.config.ts --host 127.0.0.1 --port 4192 --strictPort
