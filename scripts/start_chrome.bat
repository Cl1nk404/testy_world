@echo off
setlocal

set "CHROME_PATH=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME_PATH%" set "CHROME_PATH=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME_PATH%" set "CHROME_PATH=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"

if not exist "%CHROME_PATH%" (
  echo Google Chrome was not found.
  echo Edit CHROME_PATH in this file to point to chrome.exe.
  pause
  exit /b 1
)

set "PROFILE_DIR=%LOCALAPPDATA%\TastyWorldChrome"
if not exist "%PROFILE_DIR%" mkdir "%PROFILE_DIR%"

echo Launching a dedicated Chrome profile for Dzen automation.
echo Sign in to Dzen manually in this Chrome window once.
echo Do not share this browser profile: it contains your login session.
start "" "%CHROME_PATH%" --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 --remote-allow-origins=* --user-data-dir="%PROFILE_DIR%" --no-first-run "https://dzen.ru/profile/editor/create"

endlocal
