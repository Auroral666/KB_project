param([string]$PythonPath = $env:RAG_PYTHON)
$ErrorActionPreference = 'Stop'
if (-not $PythonPath) { $PythonPath = 'F:\anaconda\anaconda3\envs\rag-env\python.exe' }
if (-not (Test-Path -LiteralPath $PythonPath)) { throw '未找到 Python 环境，请通过 -PythonPath 指定原项目的 Python。' }
Push-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
try {
    & $PythonPath -B -X utf8 -m app.neo4j_cli
    if ($LASTEXITCODE -ne 0) { throw 'Neo4j 未就绪，请检查 Docker Desktop 和 .env。' }
    & $PythonPath -B -X utf8 -m app.cli start
    $result = $LASTEXITCODE
} finally { Pop-Location }
exit $result
