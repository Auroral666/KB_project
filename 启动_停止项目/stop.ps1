param([string]$PythonPath = $env:RAG_PYTHON)
$ErrorActionPreference = 'Stop'
if (-not $PythonPath) { $PythonPath = 'F:\anaconda\anaconda3\envs\rag-env\python.exe' }
if (-not (Test-Path -LiteralPath $PythonPath)) { throw '未找到 Python 环境，请通过 -PythonPath 指定原项目的 Python。' }
Push-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
try {
    & $PythonPath -B -X utf8 -m app.cli stop
    $result = $LASTEXITCODE
} finally { Pop-Location }
exit $result
