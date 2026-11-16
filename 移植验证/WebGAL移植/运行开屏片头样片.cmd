@echo off
setlocal
cd /d "%~dp0engine\packages\webgal"
echo I's Pure 开屏片头样片: http://127.0.0.1:4195/
echo Close this window to stop the local server.
call ..\..\node_modules\.bin\vite.cmd --config is-titleloop.vite.config.ts --host 127.0.0.1 --port 4195 --strictPort
