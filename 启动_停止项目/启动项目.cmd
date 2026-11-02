@echo off
chcp 65001 >nul
setlocal
REM ========== 1. 定位项目和 Python 环境 ==========
pushd "%~dp0.."
if not defined RAG_PYTHON set "RAG_PYTHON=F:\anaconda\anaconda3\envs\rag-env\python.exe"
if not exist "%RAG_PYTHON%" (
    echo 未找到 Python 环境，请设置 RAG_PYTHON 后重试。
    set "KB_EXIT_CODE=1"
    goto finish
)
REM ========== 2. 启动项目并确认就绪 ==========
"%RAG_PYTHON%" -B -X utf8 -m app.neo4j_cli
if errorlevel 1 (
    set "KB_EXIT_CODE=1"
    goto finish
)
"%RAG_PYTHON%" -B -X utf8 -m app.cli start
set "KB_EXIT_CODE=%ERRORLEVEL%"
:finish
popd
if not defined KB_NO_PAUSE pause
exit /b %KB_EXIT_CODE%
