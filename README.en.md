# dev-infra

[简体中文](README.md) · **English**

[![License MIT](https://img.shields.io/badge/License-MIT-blue)](LICENSE) ![Python](https://img.shields.io/badge/Python-3.14-blue) ![WSL](https://img.shields.io/badge/WSL-Ubuntu-brightgreen)

[Configuration](docs/config.en.md) · [Middleware upgrades and migrations](docs/upgrades.en.md)

One local middleware instance shared by Windows and WSL. A Python controller owns commands,
configuration, upgrade plans and presentation; Docker Compose manages containers. Windows forwards
operations to the configured WSL distribution, sharing the instance and data. dev-tools manages
application projects; dev-infra manages shared middleware.

## Services

| Service | Default version branch | Default host ports |
| --- | --- | --- |
| MySQL | 8.4 LTS | `23306` |
| PostgreSQL | 18 | `25432` |
| Redis | 8 | `26379` |
| Kafka | 4.3 | `29092` |
| RustFS | 1 | `28333` / `28346` |
| Mailpit | v1 | `21025` / `28025` |

Ports bind to `127.0.0.1` by default. Independent Docker named volumes retain data when containers
are removed.

## Installation

Requires Windows 11, PowerShell 7, WSL 2 Ubuntu and Docker Desktop WSL Integration.
Windows and WSL both use Python 3.14; other minor versions are unsupported. WSL also needs Git,
rsync, flock and Docker CLI. The controller has no third-party Python runtime dependencies.

```powershell
git clone git@github.com:hhhxxxddd/dev-infra.git
cd dev-infra
.\scripts\install.ps1
```

The installer verifies the checkout origin, deploys the instance to `/opt/dev-infra`, installs the
Windows controller at `%USERPROFILE%\.local\share\dev-infra\app`, and adds its entrypoint to user PATH. A new
terminal can invoke it with `-NoProfile`. The previous Profile forwarding function is removed.
Deployment retains local settings, version overrides, backups and volumes without restarting services.
Each deployment records its native interpreter in `.python`. A private WSL controller runtime can
live in `/opt/dev-infra/host/` and is preserved during deployment. `dev-infra self status` shows the
actual Python version and path. If WSL Python is absent from PATH, the first Windows installation
can use `.\scripts\install.ps1 -WslPython <WSL-Python-3.14-path>`.

Install only the WSL entrypoint:

```bash
sudo bash scripts/install.sh
```

Or explicitly select the native WSL interpreter:

```bash
sudo DEV_INFRA_PYTHON=/path/to/python3.14 bash scripts/install.sh
```

## Daily commands

```text
dev-infra                         # Defaults to list
dev-infra list
dev-infra show mysql              # Details and connections; passwords masked
dev-infra show mysql --secrets     # Reveal connection passwords
dev-infra show s3 --open           # Open the web page
dev-infra start                   # All services by default
dev-infra start core
dev-infra stop kafka
dev-infra restart postgres
dev-infra remove mailpit          # Remove the container, retain data
dev-infra logs kafka -f
dev-infra check                   # Read-only environment and configuration checks
dev-infra check --updates         # Read-only compatible release checks
dev-infra help upgrade
```

Services: `mysql postgres redis kafka s3 mailpit`. Groups: `core` (first four), `extra` (last two),
`all`. Windows transparently uses the shared WSL backend. WSL operations on the `/opt` instance
usually require `sudo`. Queries, upgrade previews and help never create configuration, pull images
or start containers. Queries and operation results support `--json`, except raw logs and Compose output.

## Middleware upgrades

```text
dev-infra check --updates
dev-infra upgrade --dry-run
dev-infra upgrade                 # Upgrade compatible branches of all services
dev-infra upgrade redis           # Upgrade one service
dev-infra upgrade postgres --to 18.6 --dry-run
dev-infra upgrade postgres --to 18.6
dev-infra upgrade --no-backup      # Explicitly skip database backups this time
```

`upgrade` resolves stable releases, including newer fixed tags, without editing repository
`versions.env` first. It validates, backs up databases, pulls every target image, saves versions,
recreates affected services and waits for health checks. Concrete versions and SHA256 digests are
stored in local `versions.local.env`, which controller deployments retain. RustFS upgrades include
the companion client.

MySQL stays within the current LTS branch, Kafka within its current minor version; PostgreSQL,
Redis, RustFS and Mailpit stay within their current major version. Changes outside these scopes
report migration requirements and stop before reusing old volumes. See
[Middleware upgrades and migrations](docs/upgrades.en.md) for migrations, volume cutover and recovery.

## Configuration and data

```text
dev-infra config                  # User preferences and defaults
dev-infra config edit
dev-infra config check
dev-infra config edit --instance  # Ports, accounts and volumes
dev-infra config show --versions  # Local upgraded versions
dev-infra data                    # Volumes, sizes and container references
dev-infra data backup mysql
dev-infra data reset redis --dry-run
dev-infra data reset redis --yes
dev-infra data prune --dry-run
dev-infra data prune --yes        # Unreferenced obsolete volumes owned by this instance
```

Preferences live in Windows `%USERPROFILE%\.config\dev-infra\config.toml` or the invoking WSL user's
`~/.config/dev-infra/config.toml`. Chinese is the default; set `language = "en"` for English.
Editor precedence: configured argv, VISUAL, EDITOR, then Windows Notepad / WSL vi.
Set `operation.backup = false` to disable default upgrade backups; `--backup` / `--no-backup`
override the policy for one command. The default is true. A stopped database cannot be backed up;
start it first or explicitly skip the backup.

Instance `.env`, version overrides `versions.local.env`, operation records `.state/`, backups
`backup/` and volumes remain local. Default development accounts are in `.env.example`;
`show --secrets` displays connection declarations. Changing `.env` passwords does not update
existing database accounts; update those accounts separately. See [Configuration](docs/config.en.md).

## Controller updates

Pull source code in the checkout before deploying the controller:

```text
git pull --ff-only
dev-infra self update
dev-infra self status
```

Use `dev-infra self update --source <checkout>` if the recorded source is unavailable. Windows
updates both the Windows controller and WSL backend; WSL updates only the backend. This retains
instance data and does not upgrade middleware.

## Development and verification

The source separates commands, service metadata, preferences, instance declarations, planning,
Docker, data operations and presentation. Release checks and upgrade execution share a plan;
mutations use an instance-scoped lock.

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m unittest discover -v tests
uvx ruff check src scripts/dev-infra.py tests
uvx ruff format --check src scripts/dev-infra.py tests
```

WSL: `PYTHONPATH="$PWD/src" python3.14 -m unittest discover -v tests`.
Real lifecycle check: `python3.14 tests/integration/lifecycle.py`, using an installed Redis image,
an isolated Compose project and a temporary volume, with no host ports and cleanup on exit.
See [Development](docs/development.en.md).

## Uninstall

```powershell
.\scripts\uninstall.ps1
```

Removes entrypoints and the user PATH entry; retains program files, preferences, instance
configuration, backups and Docker volumes.

## License

This project is licensed under the [MIT License](LICENSE).
