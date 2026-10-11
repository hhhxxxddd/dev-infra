function Resolve-DevInfraPython {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string] $AppRoot)

    $configured = [Environment]::GetEnvironmentVariable('DEV_INFRA_PYTHON', 'Process')
    $binding = Join-Path $AppRoot '.python'
    if ($null -ne $configured) {
        $pythonPath = $configured
    } elseif (Get-Item -LiteralPath $binding -Force -ErrorAction SilentlyContinue) {
        $pythonPath = ([string](Get-Content -LiteralPath $binding -Raw -ErrorAction Stop)).Trim()
    } else {
        $pythonPath = (Get-Command python -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
    }
    if ([string]::IsNullOrWhiteSpace($pythonPath)) {
        throw 'Python 绑定为空；请通过 DEV_INFRA_PYTHON 指定外部 Windows Python 3.14。'
    }
    $resolved = & $pythonPath -I -S (Join-Path $PSScriptRoot 'check-python.py') win32
    if ($LASTEXITCODE -ne 0 -or -not $resolved) {
        throw '需要完整的 Windows 原生 Python 3.14；失效的绑定不会自动回退。'
    }
    return $resolved.Trim()
}
