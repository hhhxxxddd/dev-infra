# 配置

[English](config.en.md) · [返回 README](../README.md)

## 分层与优先级

| 文件 | 职责 | 工具部署 |
| --- | --- | --- |
| 用户 `config.toml` | 语言、编辑器、发行版、操作策略 | 保留 |
| `/opt/dev-infra/.env` | 端口、账号、实例卷名 | 保留 |
| 仓库 `versions.env` | 默认镜像版本与卷名 | 更新 |
| `/opt/dev-infra/versions.local.env` | 本机升级后的版本和摘要 | 保留 |
| `/opt/dev-infra/.state/` | 卷归属记录、升级记录、操作锁 | 保留 |
| `/opt/dev-infra/backup/` | 数据库逻辑备份 | 保留 |

实例默认值来自 `.env.example` 与 `versions.env`，`.env` 覆盖实例值，`versions.local.env`
最后覆盖镜像版本。配置按数据解析，不执行 shell 内容；未知字段、重复端口、重复卷名、非法
版本或端口会被拒绝。`config`、`list`、`show`、`check`、`data list` 和 `--dry-run` 不创建文件。

## 用户偏好

Windows：`%USERPROFILE%\.config\dev-infra\config.toml`。
WSL：`$XDG_CONFIG_HOME/dev-infra/config.toml`，未设置时使用 `~/.config/dev-infra/config.toml`。
WSL sudo 保留调用用户的偏好范围；Windows 转发携带语言和操作策略，不把偏好文件交给后端。

```toml
language = "zh"
editor = []

[wsl]
distro = "Ubuntu"

[operation]
wait_timeout = 240
backup = true
```

- `language`：`zh` / `en`，默认中文；只通过配置切换。
- `editor`：非空字符串组成的 argv 数组；空数组依次尝试 VISUAL、EDITOR、Notepad / vi。
- `wsl.distro`：Windows 操作的共享后端，默认 Ubuntu。
- `operation.wait_timeout`：启动与健康验证超时，整数 1～3600 秒，默认 240。
- `operation.backup`：升级数据库前是否备份，默认 true；`--backup` / `--no-backup` 覆盖本次策略。

```text
dev-infra config
dev-infra config edit
dev-infra config check --json
dev-infra --config path/to/config.toml help
```

编辑器示例：`editor = ["code", "--wait"]`。WSL 默认 vi；编辑本机偏好时使用 sudo 调用用户身份。
配置损坏时仍可用 `config edit` 修复。

## 实例配置

```text
dev-infra config show --instance
dev-infra config edit --instance
dev-infra config check --instance
```

支持字段来自 `.env.example` 与 `versions.env`。包括绑定地址、时区、服务端口、账号、数据库名、
Kafka Cluster ID、S3 存储桶、Mailpit 保留数量，以及六个 `*_DATA_VOLUME`。
密码与密钥在 `config show --instance` 中隐藏；编辑打开完整文件，`show --secrets` 显示连接声明。
启动或重建使用新的端口配置。数据库密码变更需先在数据库内同步，配置文件不修改已有账号。

## 版本覆盖

```text
dev-infra config show --versions
dev-infra config edit --versions
dev-infra config check --versions
```

只接受 `MYSQL_VERSION`、`POSTGRES_VERSION`、`REDIS_VERSION`、`KAFKA_VERSION`、`RUSTFS_VERSION`、
`RUSTFS_RC_VERSION`、`MAILPIT_VERSION`。稳定数字标签可以带 `v` 前缀与 SHA256 摘要。

```dotenv
POSTGRES_VERSION=18.6
```

常规升级使用 `upgrade` 自动保存明确版本和摘要。跨版本迁移验收后，可以在此声明新版本，
并在实例 `.env` 中指定迁移完成的新卷，再执行 `start`。旧卷范围不匹配时，启动也会拒绝
直接复用。步骤见[升级与迁移](upgrades.md)。
