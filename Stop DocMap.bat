@echo off
rem Double-click to stop DocMap.
title DocMap
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop.ps1"
