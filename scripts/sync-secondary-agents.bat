@echo off
setlocal EnableExtensions
REM Clone or fast-forward verified secondary repositories only; do not execute them.
set "ROOT=%~dp0.."
set "TARGET=%ROOT%\agents\secondary"
if not exist "%TARGET%" mkdir "%TARGET%"
call :sync cai https://github.com/aliasrobotics/cai.git
call :sync strix https://github.com/usestrix/strix.git
call :sync nebula https://github.com/BerylliumSec/nebula.git
call :sync pentestgpt https://github.com/GreyDGL/PentestGPT.git
call :sync hexstrike https://github.com/0x4m4/hexstrike-ai.git
call :sync pentagi https://github.com/vxcontrol/pentagi.git
echo.
echo Secondary repositories are in: %TARGET%
echo Review every upstream README and license before installing dependencies.
exit /b 0

:sync
if exist "%TARGET%\%~1\.git" (
  echo Updating %~1
  git -C "%TARGET%\%~1" pull --ff-only
) else if exist "%TARGET%\%~1" (
  echo Skipping %~1: destination exists but is not a Git checkout
) else (
  echo Cloning %~1
  git clone --depth 1 "%~2" "%TARGET%\%~1"
)
exit /b 0
