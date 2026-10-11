[CmdletBinding()]
param([string] $Distro = 'Ubuntu', [string] $WslPython = '')

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$origin = (& git -C $repoRoot remote get-url origin).Trim()
if ($LASTEXITCODE -ne 0 -or $origin -notmatch '^(git@github\.com:|https://github\.com/)hhhxxxddd/dev-infra(\.git)?$') {
    throw '仓库来源未经验证。'
}
$pythonPath = (Get-Command python -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
& $pythonPath -c 'import sys; raise SystemExit(sys.version_info[:2] != (3, 14))'
if ($LASTEXITCODE -ne 0) { throw '需要 Python 3.14。' }
$wslRepoRoot = (& wsl.exe -d $Distro -u root --exec wslpath -a $repoRoot).Trim()
if ($LASTEXITCODE -ne 0) { throw '无法转换源码路径。' }
if ($WslPython) {
    & wsl.exe -d $Distro -u root --exec env "DEV_INFRA_PYTHON=$WslPython" bash "$wslRepoRoot/scripts/install.sh"
} else {
    & wsl.exe -d $Distro -u root --exec bash "$wslRepoRoot/scripts/install.sh"
}
if ($LASTEXITCODE -ne 0) { throw 'WSL 安装失败。' }

$userRoot = [Environment]::GetFolderPath('UserProfile')
$installBase = Join-Path $userRoot '.local/share/dev-infra'
$appRoot = Join-Path $installBase 'app'
$binRoot = Join-Path $installBase 'bin'
New-Item -ItemType Directory -Path $appRoot,$binRoot -Force | Out-Null
foreach ($name in @('src','scripts','docs','README.md','README.en.md','LICENSE','.env.example','versions.env','compose.yaml','pyproject.toml')) {
    $source = Join-Path $repoRoot $name
    if (Test-Path -LiteralPath $source) { Copy-Item -LiteralPath $source -Destination $appRoot -Recurse -Force }
}
[IO.File]::WriteAllText((Join-Path $appRoot '.python'), $pythonPath, [Text.UTF8Encoding]::new($false))
[IO.File]::WriteAllText((Join-Path $appRoot '.source'), $repoRoot, [Text.UTF8Encoding]::new($false))
$pwshPath = (Get-Command pwsh -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
$entry = Join-Path $appRoot 'scripts/dev-infra.ps1'
$launcher = "@echo off`r`n`"$pwshPath`" -NoProfile -File `"$entry`" %*`r`n"
[IO.File]::WriteAllText((Join-Path $binRoot 'dev-infra.cmd'), $launcher, [Text.UTF8Encoding]::new($false))
$userPath = [string][Environment]::GetEnvironmentVariable('Path','User')
if ($binRoot -notin @($userPath -split ';')) {
    [Environment]::SetEnvironmentVariable('Path', ($userPath.TrimEnd(';') + ';' + $binRoot).TrimStart(';'), 'User')
}
if ($binRoot -notin @($env:Path -split ';')) { $env:Path += ";$binRoot" }

# Remove the previous profile-only forwarding function.
$profilePath = $PROFILE.CurrentUserCurrentHost
if (Test-Path -LiteralPath $profilePath) {
    $content = Get-Content -LiteralPath $profilePath -Raw
    $pattern = '(?ms)^# >>> dev-infra >>>.*?^# <<< dev-infra <<<\r?\n?'
    [IO.File]::WriteAllText($profilePath, [regex]::Replace($content,$pattern,'').TrimEnd() + "`r`n", [Text.UTF8Encoding]::new($false))
}
$preferences = Join-Path $userRoot '.config/dev-infra/config.toml'
if (-not (Test-Path -LiteralPath $preferences)) {
    New-Item -ItemType Directory -Path (Split-Path -Parent $preferences) -Force | Out-Null
    $settings = "language = `"zh`"`neditor = []`n`n[wsl]`ndistro = $($Distro | ConvertTo-Json -Compress)`n`n[operation]`nwait_timeout = 240`nbackup = true`n"
    [IO.File]::WriteAllText($preferences, $settings, [Text.UTF8Encoding]::new($false))
}
Write-Host "dev-infra 已安装到 $appRoot；新终端通过 PATH 使用命令。"
