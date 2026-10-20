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
版本或端口会被拒绝。`config show`、`list`、`show`、`check` 和 `data list` 不创建文件；`config` 默认执行 show。

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
- `operation.backup`：升级数据库前是否备份，默认 true；`upgrade` 或 `check --updates` 的 `--backup` / `--no-backup` 覆盖本次策略。

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

托管启动、重启、中间件升级和数据重置成功启动 S3 后，会自动删除已成功退出的 `s3-permissions` 初始化容器。S3 仍等待权限初始化成功后才启动；后续 Compose 启动会按需重建初始化容器，不删除数据卷或停止正在运行的 S3。Compose 启动或权限初始化失败时保留初始化容器供排查。`compose` 透传保持 Docker Compose 原生行为。

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

## 安装与工具维护

### 安装要求与位置

Windows 使用 Windows 11、PowerShell 7、WSL 2 Ubuntu 和 Docker Desktop WSL Integration。WSL
需要 rsync、flock 和 Docker CLI；Git 源码安装还需要 Git。两端均使用已有原生 Python 3.14，不兼容其他次版本，
控制程序无第三方 Python 运行依赖。其他 WSL 发行版可通过安装器 `-Distro` 参数指定。

```powershell
git clone https://github.com/hhhxxxddd/dev-infra.git
cd dev-infra
.\scripts\install.ps1
```

安装器验证 Git origin 或发行包逐文件清单，将共享后端部署到 `/opt/dev-infra`，将 Windows 控制程序部署到
`%USERPROFILE%\.local\share\dev-infra\app`，将入口加入用户 PATH，并移除旧 Profile 转发函数。
新终端在 `-NoProfile` 下也可使用命令。部署不重启服务，保留本机配置、版本覆盖、归属记录、
备份与数据卷。

也可从官方渠道下载完整 ZIP，校验后解压并使用同一安装器，详见[发行包与校验](releases.md)。

只部署 WSL：

```bash
sudo bash scripts/install.sh
```

### 外部解释器绑定

两端按明确指定的 `DEV_INFRA_PYTHON`、已有原生 `.python` 绑定、PATH 的顺序选择解释器。
明确路径或已有绑定失效时直接报错。安装器检查平台、Python 3.14 版本范围和所需标准库，
将解释器的真实绝对路径保存到部署目录的 `.python`。安装、更新和卸载均不安装、升级或删除
外部 Python。`dev-infra self status` 显示实际版本和路径。

Windows 的进程环境变量只指定 Windows 解释器，WSL 用独立参数：

```powershell
$env:DEV_INFRA_PYTHON = '<Windows-Python3.14-path>'
.\scripts\install.ps1 -WslPython /path/to/python3.14
Remove-Item Env:DEV_INFRA_PYTHON
```

WSL 原生安装可以显式指定：

```bash
sudo DEV_INFRA_PYTHON=/path/to/python3.14 bash scripts/install.sh
```

WSL 可以与 dev-tools 共用外部基础 Python，应用代码、依赖和配置保持独立。共享解释器应
位于独立的运行时目录，不放在另一个应用的私有部署目录中。外部 Python 更新到新真实路径后，
按上述方式重新运行安装器更新绑定，再执行 `self status` 验证；单独切换符号链接不会改变绑定。
历史私有 `host/` 目录在部署时保留。

### 工具更新与卸载

直接获取新代码并部署工具：

```text
dev-infra -v
dev-infra self upgrade
dev-infra self status
```

Git 安装要求官方 origin、干净工作区和跟踪 origin 的分支；更新仅快进，不覆盖本地修改。发行包安装下载并校验官方最新稳定 Release 后部署。`self status` 显示当前渠道，详见[工具更新渠道](releases.md#两种工具更新渠道)。`self update` 仅重新部署当前代码；`-v` / `--version` 只输出工具版本。Scoop 安装由 Scoop 更新，清单由 hxd-box 维护。

用 `--source <目录>` 可指定官方 Git 源码或已校验的解压包；显式指定的发行包直接部署。Windows 更新同时部署
Windows 控制程序和 WSL 后端；WSL 更新只部署后端。此操作保留实例数据，不升级中间件。
部署复用已有本平台解释器绑定；变更外部解释器路径时直接重跑原生安装器。

在源码或发行包目录卸载入口：

```powershell
.\scripts\uninstall.ps1
```

原生 WSL 使用 `sudo bash scripts/uninstall.sh`。卸载仅移除命令入口和 Windows 用户 PATH 项，
保留程序文件、偏好、实例配置、版本覆盖、备份、Docker 数据卷及外部 Python。
