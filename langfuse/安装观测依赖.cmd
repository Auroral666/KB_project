@echo off
chcp 65001 >nul
setlocal
REM ========== 1. 读取原环境依赖版本 ==========
pushd "%~dp0"
if not defined RAG_PYTHON set "RAG_PYTHON=F:\anaconda\anaconda3\envs\rag-env\python.exe"
if not exist temp mkdir temp
"%RAG_PYTHON%" -B -X utf8 -m pip freeze > temp\install-constraints.txt
if errorlevel 1 goto finish
REM ========== 2. 只安装到独立目录，不修改原环境 ==========
"%RAG_PYTHON%" -B -X utf8 -m pip install --upgrade --target "%~dp0.packages" -c temp\install-constraints.txt -r requirements.txt
:finish
set "KB_EXIT_CODE=%ERRORLEVEL%"
popd
if not defined KB_NO_PAUSE pause
exit /b %KB_EXIT_CODE%
