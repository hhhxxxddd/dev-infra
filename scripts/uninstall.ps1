[CmdletBinding()]
param(
    [string] $Distro = 'Ubuntu'
)

$ErrorActionPreference = 'Stop'
$profilePath = $PROFILE.CurrentUserCurrentHost
$startMarker = '# >>> dev-infra >>>'
$endMarker = '# <<< dev-infra <<<'

if (Test-Path -LiteralPath $profilePath) {
    $content = Get-Content -LiteralPath $profilePath -Raw
    $pattern = "(?ms)^$([regex]::Escape($startMarker)).*?^$([regex]::Escape($endMarker))\r?\n?"
    $updated = [regex]::Replace($content, $pattern, '').TrimEnd()
    [IO.File]::WriteAllText(
        $profilePath,
        $(if ($updated) { "$updated`r`n" } else { '' }),
        [Text.UTF8Encoding]::new($false)
    )
}

& wsl.exe -d $Distro -u root -- rm -f /usr/local/bin/dev-infra
if ($LASTEXITCODE -ne 0) {
    throw "移除 WSL 命令失败，退出码：$LASTEXITCODE"
}

Write-Host '已移除 Windows 和 WSL 命令入口。/opt/dev-infra 及其数据均已保留。'
