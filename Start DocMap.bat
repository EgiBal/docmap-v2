@echo off
rem Double-click to start DocMap in the background and open it in the browser.
title DocMap
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1"
