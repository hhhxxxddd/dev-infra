[CmdletBinding()]
param([string] $Distro = 'Ubuntu')
$ErrorActionPreference = 'Stop'
$binRoot = [IO.Path]::GetFullPath((Join-Path ([Environment]::GetFolderPath('UserProfile')) '.local/share/dev-infra/bin'))
$entry = [IO.Path]::GetFullPath((Join-Path $binRoot 'dev-infra.cmd'))
if ([IO.Path]::GetDirectoryName($entry) -ne $binRoot) { throw '入口路径无效。' }
if (Test-Path -LiteralPath $entry) { Remove-Item -LiteralPath $entry -Force }
$userPath = [Environment]::GetEnvironmentVariable('Path','User')
[Environment]::SetEnvironmentVariable('Path', (@($userPath -split ';' | Where-Object { $_ -and $_ -ne $binRoot }) -join ';'), 'User')
& wsl.exe -d $Distro -u root --exec bash /opt/dev-infra/scripts/uninstall.sh
if ($LASTEXITCODE -ne 0) { throw 'WSL 卸载入口失败。' }
Write-Host '已移除命令入口；配置、程序文件、备份和数据卷均已保留。'
