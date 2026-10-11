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
`config`, `list`, `show`, `check`, `data list` and `--dry-run` do not create files.

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
  override it for one command.

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
