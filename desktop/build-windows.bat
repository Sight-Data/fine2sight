@echo off
chcp 65001 >nul
REM 在 Windows 上打包成 .exe(需 Python3 已加入 PATH)。
REM 产物:dist\帆软报表转换器.exe(单文件,无散落 DLL/目录)
setlocal
cd /d "%~dp0"

python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto :err

REM 每次编译:自增 version.py 的 PATCH + 写构建戳 _build.py
for /f "delims=" %%v in ('python ..\_bump_and_stamp.py') do set "VER=%%v"
echo [VER] %VER%

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
del /q *.spec 2>nul

pyinstaller --noconfirm --clean --windowed --onefile ^
  --name "帆软报表转换器" ^
  --icon "assets\icon.ico" ^
  --collect-all webview ^
  --add-data "web;web" ^
  --paths ".." ^
  --hidden-import convert ^
  --hidden-import version ^
  --hidden-import _build ^
  app.py
if errorlevel 1 goto :err

echo.
echo [OK] 完成:dist\帆软报表转换器.exe  (v%VER%) — 单个可执行文件,拷给用户即可双击运行。
echo      需系统已装 "WebView2 Runtime"(Win11/多数 Win10 自带;没有可从微软官网装)。
echo      注:单文件首次/冷启动会先解包到临时目录,稍慢;个别杀软可能误报,如遇请加白。
goto :eof

:err
echo.
echo [FAIL] 打包失败,请看上面的报错。
exit /b 1
