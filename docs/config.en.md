# Configuration

[中文](config.md) · [README](../README.en.md)

## Layers and precedence

| File | Responsibility | Controller deployment |
| --- | --- | --- |
| User `config.toml` | Language, editor, distribution, operation policy | Retained |
| `/opt/dev-infra/.env` | Ports, accounts, instance volume names | Retained |
| Repository `versions.env` | Default image versions and volumes | Updated |
| `/opt/dev-infra/versions.local.env` | Locally upgraded versions and digests | Retained |
| `/opt/dev-infra/.state/` | Volume ownership, upgrade records, operation lock | Retained |
| `/opt/dev-infra/backup/` | Logical database backups | Retained |

Instance defaults come from `.env.example` and `versions.env`. `.env` overrides instance values;
`versions.local.env` overrides image versions last. Files are parsed as data, never sourced as shell
code. Unknown fields, duplicate ports or volumes, and invalid versions or ports are rejected.
`config show`, `list`, `show`, `check` and `data list` do not create files; `config` defaults to show.

## User preferences

Windows: `%USERPROFILE%\.config\dev-infra\config.toml`.
WSL: `$XDG_CONFIG_HOME/dev-infra/config.toml`, defaulting to `~/.config/dev-infra/config.toml`.
WSL sudo retains the invoking user's preference scope. Windows forwards language and operation
policy rather than passing its preferences file to the backend.

```toml
language = "zh"
editor = []

[wsl]
distro = "Ubuntu"

[operation]
wait_timeout = 240
backup = true
```

- `language`: `zh` / `en`, default Chinese; selected through configuration only.
- `editor`: argv array of nonempty strings. An empty array tries VISUAL, EDITOR, then Notepad / vi.
- `wsl.distro`: shared backend for Windows operations, default Ubuntu.
- `operation.wait_timeout`: startup and health timeout, integer 1–3600 seconds, default 240.
- `operation.backup`: database backups before upgrades, default true; `--backup` / `--no-backup`
  on `upgrade` or `check --updates` override it for one command.

```text
dev-infra config
dev-infra config edit
dev-infra config check --json
dev-infra --config path/to/config.toml help
```

Editor example: `editor = ["code", "--wait"]`. WSL defaults to vi. Editing user preferences under
sudo uses the invoking user's identity. `config edit` can repair an invalid preferences file.

## Instance configuration

```text
dev-infra config show --instance
dev-infra config edit --instance
dev-infra config check --instance
```

Fields are defined by `.env.example` and `versions.env`: bind address, timezone, ports, accounts,
database names, Kafka Cluster ID, S3 bucket, Mailpit retention and the six `*_DATA_VOLUME` fields.
`config show --instance` masks passwords and secrets. Editing opens the complete file;
`show --secrets` reveals connection declarations. Start or recreate services to apply new ports.
Password changes require updating database accounts separately; files do not modify existing accounts.

## Version overrides

```text
dev-infra config show --versions
dev-infra config edit --versions
dev-infra config check --versions
```

Accepts only `MYSQL_VERSION`, `POSTGRES_VERSION`, `REDIS_VERSION`, `KAFKA_VERSION`, `RUSTFS_VERSION`,
`RUSTFS_RC_VERSION`, `MAILPIT_VERSION`. Stable numeric tags may include a `v` prefix and SHA256 digest.

```dotenv
POSTGRES_VERSION=18.6
```

Use `upgrade` to save concrete versions and digests automatically. After validating a migration,
declare the new version here, select the migrated volume in instance `.env`, then run `start`.
Startup also rejects directly reusing a volume with an incompatible recorded version scope.
See [Upgrades and migrations](upgrades.en.md).

## Installation and controller maintenance

### Requirements and locations

Windows requires Windows 11, PowerShell 7, WSL 2 Ubuntu and Docker Desktop WSL Integration. WSL
needs rsync, flock and Docker CLI; Git source installations also need Git. Both platforms use existing native Python 3.14; other minor
versions are unsupported. The controller has no third-party Python runtime dependencies. Select
another WSL distribution with the installer's `-Distro` parameter.

```powershell
git clone https://github.com/hhhxxxddd/dev-infra.git
cd dev-infra
.\scripts\install.ps1
```

The installer verifies Git origin or the release inventory, deploys the shared backend to `/opt/dev-infra`, installs the
Windows controller at `%USERPROFILE%\.local\share\dev-infra\app`, adds the entrypoint to user PATH,
and removes the previous Profile forwarding function. A new terminal can use the command with
`-NoProfile`. Deployment retains local configuration, version overrides, ownership records,
backups and volumes without restarting services.

You can also download the complete ZIP from the official channel, verify and extract it, then use
the same installer. See [Release packages and verification](releases.en.md).

Deploy WSL only:

```bash
sudo bash scripts/install.sh
```

### External interpreter bindings

Both platforms select an explicitly set `DEV_INFRA_PYTHON`, an existing native `.python` binding,
then PATH. An invalid explicit path or existing binding fails without fallback. The installer
checks the native platform, Python 3.14 range and required standard-library modules, then records
the real absolute interpreter path in the deployed `.python` file. Installation, updates and
removal never install, upgrade or delete external Python. `dev-infra self status` shows its actual
version and path.

The Windows process environment selects only Windows Python; WSL uses a separate parameter:

```powershell
$env:DEV_INFRA_PYTHON = '<Windows-Python3.14-path>'
.\scripts\install.ps1 -WslPython /path/to/python3.14
Remove-Item Env:DEV_INFRA_PYTHON
```

Native WSL installation can select an interpreter explicitly:

```bash
sudo DEV_INFRA_PYTHON=/path/to/python3.14 bash scripts/install.sh
```

WSL may share an external base Python with dev-tools; application code, dependencies and
configuration remain separate. Keep shared interpreters in an independent runtime directory,
outside another application's private deployment. When Python moves to a new real path, rerun
the installer as above and verify `self status`; changing a symbolic link alone does not alter
the recorded binding. Deployment retains legacy private `host/` directories.

### Controller updates and removal

Fetch new code and deploy the controller directly:

```text
dev-infra -v
dev-infra self upgrade
dev-infra self status
```

Git installations require the official origin, a clean worktree and a branch tracking origin; updates only fast-forward without overwriting local changes. Package installations download and verify the latest official stable Release before deployment. `self status` reports the channel; see [Controller update channels](releases.en.md#two-controller-update-channels). `self update` only redeploys current code; `-v` / `--version` only print the controller version. Scoop installations update through Scoop, with manifests maintained in hxd-box.

Use `--source <directory>` to select official Git source or a verified extracted package; an explicit package is deployed directly. Windows
updates both the Windows controller and WSL backend; WSL updates only the backend. This retains
instance data and does not upgrade middleware. Deployment reuses existing native bindings;
rerun the native installer directly when changing an external interpreter path.

Remove entrypoints from a source checkout or extracted package:

```powershell
.\scripts\uninstall.ps1
```

Native WSL uses `sudo bash scripts/uninstall.sh`. Removal only deletes entrypoints and the Windows
user PATH entry. Program files, preferences, instance configuration, version overrides, backups,
Docker volumes and external Python are retained.
