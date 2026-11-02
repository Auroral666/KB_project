@echo off
chcp 65001 >nul
setlocal
REM ========== 1. 定位独立观测入口 ==========
pushd "%~dp0"
if not defined RAG_PYTHON set "RAG_PYTHON=F:\anaconda\anaconda3\envs\rag-env\python.exe"
"%RAG_PYTHON%" -B -X utf8 "%~dp0run.py" check
set "KB_EXIT_CODE=%ERRORLEVEL%"
popd
if not defined KB_NO_PAUSE pause
exit /b %KB_EXIT_CODE%
