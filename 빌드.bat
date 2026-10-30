@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 데스크탑 펫 exe 만들기
echo.
echo  ===== 데스크탑 펫 exe 만들기 =====
echo.

set PY=
for %%V in (3.12 3.13 3.11 3) do (
  if not defined PY (
    py -%%V -c "import sys" >nul 2>nul && set "PY=py -%%V"
  )
)
if not defined PY (
  python -c "import sys" >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo [오류] 파이썬이 없어요. https://www.python.org 에서 3.12 버전을 설치해 주세요.
  echo        설치 첫 화면에서 "Add python.exe to PATH" 를 꼭 체크하세요.
  pause
  exit /b
)
echo  사용할 파이썬: %PY%
%PY% --version
echo.

echo  [1/3] 작업 공간 만드는 중... (30초 정도)
if not exist ".buildenv\Scripts\python.exe" %PY% -m venv .buildenv
if not exist ".buildenv\Scripts\python.exe" goto fail
set "VPY=.buildenv\Scripts\python.exe"
echo        완료
echo.

echo  [2/3] 필요한 프로그램 내려받는 중... (5~10분, 아래에 진행 막대가 보여요)
%VPY% -m pip install --upgrade pip --disable-pip-version-check
%VPY% -m pip install --disable-pip-version-check PySide6-Essentials pillow pillow-heif numpy onnxruntime pyinstaller
if errorlevel 1 goto fail
echo        완료
echo.

echo  [3/3] exe 만드는 중... (2~5분, 글자가 많이 지나가요)
%VPY% -m PyInstaller --noconfirm --clean --onefile --windowed --name DesktopPet --icon icon.ico --collect-binaries onnxruntime --collect-all pillow_heif --exclude-module tkinter --exclude-module matplotlib --exclude-module scipy --exclude-module pandas desktop_pet.py
if errorlevel 1 goto fail

copy /y "dist\DesktopPet.exe" "데스크탑펫.exe" >nul
rmdir /s /q build 2>nul
del DesktopPet.spec 2>nul
echo.
echo  ===== 완성! 이 폴더의 "데스크탑펫.exe" 를 쓰면 돼요 =====
echo  다른 컴퓨터에는 데스크탑펫.exe 파일 하나만 보내면 돼요.
echo.
start "" explorer /select,"%~dp0데스크탑펫.exe"
pause
exit /b

:fail
echo.
echo [오류] 만드는 중에 문제가 생겼어요. 이 창을 캡처해서 보여 주세요.
pause
