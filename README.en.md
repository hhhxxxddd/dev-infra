# dev-infra

[简体中文](README.md) · **English**

[![License MIT](https://img.shields.io/badge/License-MIT-blue)](LICENSE) [![WSL Ubuntu](https://img.shields.io/badge/WSL-Ubuntu-brightgreen)](docs/config.en.md) [![Python 3.14](https://img.shields.io/badge/Python-3.14-blue)](docs/config.en.md)

Ready-to-use local development middleware with a WSL Docker Compose backend shared by Windows and WSL: inspect connections, control services, upgrade images and manage data.

## Requirements

| Platform / dependency | Version or requirement | Purpose / scope |
| --- | --- | --- |
| Windows | Windows 11 | Windows entrypoint; unnecessary for WSL-only use |
| PowerShell | 7 or newer | Windows installer and command entrypoint |
| WSL / Ubuntu | WSL 2; verified on Ubuntu 24.04 LTS | Shared backend |
| Python | 3.14.x | Existing native external interpreter on both platforms; never installed or upgraded automatically |
| Docker | Docker + Compose v2 | WSL backend; enable WSL Integration when using Docker Desktop |
| Git | Available `git` command | Git source installation and updates |
| rsync / flock | Available in WSL | File deployment and operation locking |

## Installation

### Scoop (Windows)

Install official releases through hxd-box:

```powershell
scoop bucket add hxd-box https://github.com/hhhxxxddd/hxd-box
scoop install hxd-box/dev-infra
```

Scoop installs PowerShell automatically; prepare Python on both platforms and the WSL backend dependencies first.

### Git (Windows)

```powershell
git clone https://github.com/hhhxxxddd/dev-infra.git
cd dev-infra
.\scripts\install.ps1
```

Use `dev-infra` in a new terminal after installation; Windows operations forward to the WSL backend.
See [complete installation instructions](docs/config.en.md#installation-and-controller-maintenance) for WSL-only use, external interpreter selection and removal.

## Quick start

```text
dev-infra check
dev-infra start core
dev-infra list
dev-infra show mysql
```

`core` includes MySQL, PostgreSQL, Redis and Kafka; `extra` includes RustFS and Mailpit.
Native WSL operations on the `/opt` instance usually require `sudo`.

## Common commands

| Command | Purpose |
| --- | --- |
| `dev-infra upgrade` | Upgrade middleware |
| `dev-infra self upgrade` | Upgrade dev-infra itself |
| `dev-infra config edit --instance` | Edit instance configuration |
| `dev-infra data list` | Inspect volumes and container references |
| `dev-infra -v` / `dev-infra help` | Show the version or help; running without arguments also shows help |

Removing containers retains Docker volumes; explicit data cleanup deletes data.
Controller installation and updates retain local configuration, external Python and instance data without restarting middleware.

Chinese is the default; set `language = "en"` in user `config.toml` for English.
User preferences such as language and editor are stored separately from instance configuration; see [configuration](docs/config.en.md).

## Documentation

[Configuration and installation](docs/config.en.md) · [Upgrades and migrations](docs/upgrades.en.md) · [CLI contract](docs/cli-contract.en.md)

[Releases and updates](docs/releases.en.md) · [Development and contributing](docs/development.en.md)
