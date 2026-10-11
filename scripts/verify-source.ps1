function Test-DevInfraPayloadName {
    param([string] $Name)
    if (-not $Name -or $Name -match '[\\<>:"|?*\x00-\x1f]' -or $Name.StartsWith('/')) { return $false }
    $parts = $Name.Split('/')
    foreach ($part in $parts) {
        if (-not $part -or $part -in @('.','..') -or $part -match '[. ]$' -or $part -match '^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\.|$)') { return $false }
        if ($part -in @('.git','.env','.python','.source','versions.local.env','.state','backup','backups','host','__pycache__','.ruff_cache','.venv','dist','build') -or $part.EndsWith('.egg-info')) { return $false }
    }
    if ($Name -match '\.py[co]$|\.local\.') { return $false }
    return $Name -in @('dev-infra','compose.yaml','versions.env','.env.example','README.md','README.en.md','LICENSE','AGENTS.md','pyproject.toml') -or $Name -match '^(src/dev_infra|scripts|config|init|docs)/'
}

function Assert-DevInfraSource {
    param([Parameter(Mandatory)][string] $Root)
    $Root = [IO.Path]::GetFullPath($Root).TrimEnd([IO.Path]::DirectorySeparatorChar)
    if (Test-Path -LiteralPath (Join-Path $Root '.git')) {
        $origin = @(& git -c "safe.directory=$Root" -C $Root remote get-url origin 2>$null)
        if ($LASTEXITCODE -ne 0 -or "$origin".Trim() -notmatch '^(git@github\.com:|https://github\.com/)hhhxxxddd/dev-infra(\.git)?$') { throw '仓库来源未经验证。' }
        $checkout = @(& git -c "safe.directory=$Root" -C $Root rev-parse --show-toplevel 2>$null)
        if ($LASTEXITCODE -ne 0 -or [IO.Path]::GetFullPath("$checkout".Trim()) -ne $Root -or -not (Test-Path -LiteralPath (Join-Path $Root 'scripts/install.sh') -PathType Leaf)) { throw '仓库来源未经验证。' }
        foreach ($directory in @('src/dev_infra','scripts','config','init','docs')) {
            $folder = Join-Path $Root $directory
            if (-not (Test-Path -LiteralPath $folder)) { continue }
            if ((Get-Item -LiteralPath $folder -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw '源码不允许符号链接。' }
            foreach ($item in @(Get-ChildItem -LiteralPath $folder -Recurse -Force)) {
                $name = [IO.Path]::GetRelativePath($Root, $item.FullName).Replace('\','/')
                if ((Test-DevInfraPayloadName $name) -and ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw '源码不允许符号链接。' }
            }
        }
        foreach ($name in @('dev-infra','compose.yaml','versions.env','.env.example','README.md','README.en.md','LICENSE','AGENTS.md','pyproject.toml')) {
            $target = Join-Path $Root $name
            if ((Test-Path -LiteralPath $target) -and ((Get-Item -LiteralPath $target -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw '源码不允许符号链接。' }
        }
        return 'git'
    }
    $receiptPath = Join-Path $Root '.release.json'
    if (-not (Test-Path -LiteralPath $receiptPath -PathType Leaf) -or (Get-Item -LiteralPath $receiptPath -Force).LinkType) { throw '发行包来源未经验证。' }
    $receipt = [IO.File]::ReadAllText($receiptPath) | ConvertFrom-Json -AsHashtable
    if (($receipt.schema_version -isnot [int] -and $receipt.schema_version -isnot [long]) -or $receipt.schema_version -ne 1 -or $receipt.repository -cne 'hhhxxxddd/dev-infra' -or $receipt.version -isnot [string] -or $receipt.version -notmatch '^\d+\.\d+\.\d+$' -or $receipt.provenance -isnot [Collections.IDictionary] -or $receipt.provenance.commit -isnot [string] -or $receipt.provenance.commit -notmatch '^([0-9a-f]{40}|[0-9a-f]{64})$' -or $receipt.provenance.dirty -isnot [bool] -or $receipt.files -isnot [Collections.IDictionary]) { throw '发行包清单无效。' }
    foreach ($required in @('dev-infra','compose.yaml','versions.env','.env.example','README.md','README.en.md','LICENSE','AGENTS.md','pyproject.toml','src/dev_infra/__init__.py','src/dev_infra/__main__.py','src/dev_infra/catalog.py','src/dev_infra/cli.py','src/dev_infra/data.py','src/dev_infra/docker.py','src/dev_infra/instance.py','src/dev_infra/operations.py','src/dev_infra/package_smoke.py','src/dev_infra/planning.py','src/dev_infra/presentation.py','src/dev_infra/registry.py','src/dev_infra/release.py','src/dev_infra/settings.py','src/dev_infra/source.py','src/dev_infra/validation.py','scripts/install.ps1','scripts/install.sh','scripts/dev-infra.ps1','scripts/dev-infra.py','scripts/check-python.py','scripts/python-runtime.ps1','scripts/python-runtime.sh','scripts/verify-source.ps1','scripts/verify-source.py','scripts/uninstall.ps1','scripts/uninstall.sh','config/mysql/my.cnf','config/postgres/postgresql.conf','config/redis/redis.conf','config/kafka/kafka.env','init/mysql/10-native-auth.sh','init/postgres/README.md')) {
        if (-not $receipt.files.Contains($required)) { throw '发行包缺少必需文件。' }
    }
    $names = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($name in $receipt.files.Keys) {
        if (-not (Test-DevInfraPayloadName $name) -or -not $names.Add($name) -or $receipt.files[$name] -isnot [string] -or $receipt.files[$name] -notmatch '^[0-9a-f]{64}$') { throw '发行包路径或校验值无效。' }
        $target = [IO.Path]::GetFullPath((Join-Path $Root $name))
        if (-not $target.StartsWith($Root + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase) -or -not (Test-Path -LiteralPath $target -PathType Leaf)) { throw '发行包文件无效。' }
        $ancestor = $target
        while ($ancestor -ne $Root) {
            if ((Get-Item -LiteralPath $ancestor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw '发行包不允许符号链接。' }
            $ancestor = Split-Path -Parent $ancestor
        }
        if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant() -cne $receipt.files[$name]) { throw '发行包文件校验失败。' }
    }
    foreach ($directory in @('src/dev_infra','scripts','config','init','docs')) {
        foreach ($file in @(Get-ChildItem -LiteralPath (Join-Path $Root $directory) -Recurse -File -Force)) {
            $name = [IO.Path]::GetRelativePath($Root, $file.FullName).Replace('\','/')
            if ((Test-DevInfraPayloadName $name) -and -not $receipt.files.Contains($name)) { throw '发行包包含清单外的文件。' }
        }
    }
    $versionMatch = [regex]::Match([IO.File]::ReadAllText((Join-Path $Root 'src/dev_infra/__init__.py')), '(?m)^__version__ = "([^"]+)"\r?$')
    $metadataMatch = [regex]::Match([IO.File]::ReadAllText((Join-Path $Root 'pyproject.toml')), '(?m)^version = "([^"]+)"\r?$')
    if (-not $versionMatch.Success -or -not $metadataMatch.Success -or $versionMatch.Groups[1].Value -cne $receipt.version -or $metadataMatch.Groups[1].Value -cne $receipt.version) { throw '发行包版本不一致。' }
    return 'release'
}
