[CmdletBinding()]
param([string] $Distro = 'Ubuntu', [string] $WslPython = '', [string] $AppRoot = '', [switch] $NoPath, [string] $PreferencesPath = '')

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
. (Join-Path $PSScriptRoot 'verify-source.ps1')
$channel = Assert-DevInfraSource $repoRoot
$userRoot = [Environment]::GetFolderPath('UserProfile')
$installBase = Join-Path $userRoot '.local/share/dev-infra'
$appRoot = if ($AppRoot) { [IO.Path]::GetFullPath($AppRoot) } else { Join-Path $installBase 'app' }
$appRoot = $appRoot.TrimEnd([IO.Path]::DirectorySeparatorChar)
if (-not [IO.Path]::IsPathFullyQualified($appRoot) -or $appRoot -eq [IO.Path]::GetPathRoot($appRoot) -or ($appRoot -ne $repoRoot -and ($appRoot.StartsWith($repoRoot + '\', [StringComparison]::OrdinalIgnoreCase) -or $repoRoot.StartsWith($appRoot + '\', [StringComparison]::OrdinalIgnoreCase)))) { throw '安装目录必须独立于源码目录。' }
if ((Get-Item -LiteralPath $appRoot -Force -ErrorAction SilentlyContinue).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw '安装目录包含无效链接。' }
foreach ($name in @('src','scripts','docs','config','init','.python','.source','.release.json','dev-infra','compose.yaml','versions.env','.env.example','README.md','README.en.md','LICENSE','AGENTS.md','pyproject.toml')) {
    $target = [IO.Path]::GetFullPath((Join-Path $appRoot $name))
    if (-not $target.StartsWith($appRoot + '\', [StringComparison]::OrdinalIgnoreCase) -or ((Get-Item -LiteralPath $target -Force -ErrorAction SilentlyContinue).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw '安装目录包含无效链接。' }
}
$binRoot = Join-Path $installBase 'bin'
. (Join-Path $PSScriptRoot 'python-runtime.ps1')
$pythonPath = Resolve-DevInfraPython -AppRoot $appRoot
$wslRepoRoot = (& wsl.exe -d $Distro -u root --exec wslpath -a $repoRoot).Trim()
if ($LASTEXITCODE -ne 0) { throw '无法转换源码路径。' }
if ($WslPython) {
    & wsl.exe -d $Distro -u root --exec env "DEV_INFRA_PYTHON=$WslPython" bash "$wslRepoRoot/scripts/install.sh"
} else {
    & wsl.exe -d $Distro -u root --exec bash "$wslRepoRoot/scripts/install.sh"
}
if ($LASTEXITCODE -ne 0) { throw 'WSL 安装失败。' }

New-Item -ItemType Directory -Path $appRoot -Force | Out-Null
if ($appRoot -ne $repoRoot) {
    foreach ($directory in @('src','scripts','docs','config','init')) {
        $target = [IO.Path]::GetFullPath((Join-Path $appRoot $directory))
        # These exact owned directories were checked above; local instance files live outside them.
        if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force }
    }
    $payload = @()
    foreach ($name in @('dev-infra','compose.yaml','versions.env','.env.example','README.md','README.en.md','LICENSE','AGENTS.md','pyproject.toml','.release.json')) {
        $source = Join-Path $repoRoot $name
        if (Test-Path -LiteralPath $source -PathType Leaf) { $payload += Get-Item -LiteralPath $source -Force }
    }
    foreach ($directory in @('src/dev_infra','scripts','docs','config','init')) {
        $payload += @(Get-ChildItem -LiteralPath (Join-Path $repoRoot $directory) -Recurse -File -Force | Where-Object { Test-DevInfraPayloadName ([IO.Path]::GetRelativePath($repoRoot, $_.FullName).Replace('\','/')) })
    }
    foreach ($file in $payload) {
        $relative = [IO.Path]::GetRelativePath($repoRoot, $file.FullName)
        $target = Join-Path $appRoot $relative
        New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
        Copy-Item -LiteralPath $file.FullName -Destination $target -Force
    }
}
[IO.File]::WriteAllText((Join-Path $appRoot '.python'), $pythonPath, [Text.UTF8Encoding]::new($false))
if ($channel -eq 'git') {
    [IO.File]::WriteAllText((Join-Path $appRoot '.source'), $repoRoot, [Text.UTF8Encoding]::new($false))
    Remove-Item -LiteralPath (Join-Path $appRoot '.release.json') -Force -ErrorAction SilentlyContinue
} else { Remove-Item -LiteralPath (Join-Path $appRoot '.source') -Force -ErrorAction SilentlyContinue }
if (-not $NoPath) {
New-Item -ItemType Directory -Path $binRoot -Force | Out-Null
$pwshPath = (Get-Command pwsh -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
$entry = Join-Path $appRoot 'scripts/dev-infra.ps1'
$launcher = "@echo off`r`n`"$pwshPath`" -NoProfile -File `"$entry`" %*`r`n"
[IO.File]::WriteAllText((Join-Path $binRoot 'dev-infra.cmd'), $launcher, [Text.UTF8Encoding]::new($false))
$userPath = [string][Environment]::GetEnvironmentVariable('Path','User')
if ($binRoot -notin @($userPath -split ';')) {
    [Environment]::SetEnvironmentVariable('Path', ($userPath.TrimEnd(';') + ';' + $binRoot).TrimStart(';'), 'User')
}
if ($binRoot -notin @($env:Path -split ';')) { $env:Path += ";$binRoot" }
}

# Remove the previous profile-only forwarding function.
$profilePath = $PROFILE.CurrentUserCurrentHost
if (-not $NoPath -and (Test-Path -LiteralPath $profilePath)) {
    $content = Get-Content -LiteralPath $profilePath -Raw
    $pattern = '(?ms)^# >>> dev-infra >>>.*?^# <<< dev-infra <<<\r?\n?'
    [IO.File]::WriteAllText($profilePath, [regex]::Replace($content,$pattern,'').TrimEnd() + "`r`n", [Text.UTF8Encoding]::new($false))
}
$preferences = if ($PreferencesPath) { [IO.Path]::GetFullPath($PreferencesPath) } else { Join-Path $userRoot '.config/dev-infra/config.toml' }
if (-not (Test-Path -LiteralPath $preferences)) {
    New-Item -ItemType Directory -Path (Split-Path -Parent $preferences) -Force | Out-Null
    $settings = "language = `"zh`"`neditor = []`n`n[wsl]`ndistro = $($Distro | ConvertTo-Json -Compress)`n`n[operation]`nwait_timeout = 240`nbackup = true`n"
    [IO.File]::WriteAllText($preferences, $settings, [Text.UTF8Encoding]::new($false))
}
Write-Host "dev-infra 已安装到 $appRoot；新终端通过 PATH 使用命令。"
