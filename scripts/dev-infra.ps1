$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$controllerRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pythonPath = (Get-Content -LiteralPath (Join-Path $controllerRoot '.python') -Raw).Trim()
& $pythonPath -X utf8 (Join-Path $PSScriptRoot 'dev-infra.py') @args
exit $LASTEXITCODE
