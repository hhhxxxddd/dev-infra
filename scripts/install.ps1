[CmdletBinding()]
param(
    [string] $Distro = 'Ubuntu'
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$profilePath = $PROFILE.CurrentUserCurrentHost
$startMarker = '# >>> dev-infra >>>'
$endMarker = '# <<< dev-infra <<<'
$quotedDistro = $Distro.Replace("'", "''")

if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    throw '未找到 wsl.exe。'
}

if ($repoRoot -notmatch '^([A-Za-z]):\\(.*)$') {
    throw "当前安装器只支持本机盘符路径：$repoRoot"
}
$drive = $Matches[1].ToLowerInvariant()
$relativePath = $Matches[2].Replace('\', '/')
$wslRepoRoot = "/mnt/$drive/$relativePath"

& wsl.exe -d $Distro -u root -- bash "$wslRepoRoot/scripts/install.sh"
if ($LASTEXITCODE -ne 0) {
    throw "WSL dev-infra 安装失败，退出码：$LASTEXITCODE"
}

$block = @"
$startMarker
function dev-infra { & wsl.exe -d '$quotedDistro' -- dev-infra @args }
$endMarker
"@

$profileDirectory = Split-Path -Parent $profilePath
if (-not (Test-Path -LiteralPath $profileDirectory)) {
    New-Item -ItemType Directory -Path $profileDirectory -Force | Out-Null
}
$content = if (Test-Path -LiteralPath $profilePath) {
    Get-Content -LiteralPath $profilePath -Raw
} else {
    ''
}
$pattern = "(?ms)^$([regex]::Escape($startMarker)).*?^$([regex]::Escape($endMarker))\r?\n?"
$content = [regex]::Replace($content, $pattern, '').TrimEnd()
$updated = if ($content) { "$content`r`n`r`n$block`r`n" } else { "$block`r`n" }
[IO.File]::WriteAllText($profilePath, $updated, [Text.UTF8Encoding]::new($false))

Write-Host "dev-infra 已安装到 WSL $Distro，并写入 PowerShell 配置：$profilePath"
Write-Host '重启 PowerShell 或执行：. $PROFILE'
