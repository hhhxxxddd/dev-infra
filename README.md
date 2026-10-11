# dev-infra

**简体中文** · [English](README.en.md)

[![License MIT](https://img.shields.io/badge/License-MIT-blue)](LICENSE) ![Python](https://img.shields.io/badge/Python-3.14-blue) ![WSL](https://img.shields.io/badge/WSL-Ubuntu-brightgreen)

[配置](docs/config.md) · [中间件升级与迁移](docs/upgrades.md)

Windows 与 WSL 共用的一套本地开发中间件。Python 控制层负责命令、配置、升级计划与展示，
Docker Compose 负责容器；Windows 命令转发到配置的 WSL 发行版，共用同一份实例与数据。
dev-tools 管应用项目，dev-infra 管共享中间件。

## 服务

| 服务 | 默认版本分支 | 默认宿主端口 |
| --- | --- | --- |
| MySQL | 8.4 LTS | `23306` |
| PostgreSQL | 18 | `25432` |
| Redis | 8 | `26379` |
| Kafka | 4.3 | `29092` |
| RustFS | 1 | `28333` / `28346` |
| Mailpit | v1 | `21025` / `28025` |

端口默认绑定 `127.0.0.1`。数据使用独立 Docker named volume；删除容器会保留数据。

## 安装

需要 Windows 11、PowerShell 7、WSL 2 Ubuntu、Docker Desktop WSL Integration。
Windows 与 WSL 均使用 Python 3.14，不支持其他次版本。
WSL 提供 Git、rsync、flock 和 Docker CLI。
控制程序无第三方 Python 运行依赖。

```powershell
git clone git@github.com:hhhxxxddd/dev-infra.git
cd dev-infra
.\scripts\install.ps1
```

安装器验证仓库 origin，将实例部署到 `/opt/dev-infra`，将 Windows 控制程序部署到
`%USERPROFILE%\.local\share\dev-infra\app`，并将入口加入用户 PATH。新终端可以在 `-NoProfile` 下使用命令。
已有 Profile 转发函数会被移除。部署不重启服务，并保留本机配置、版本覆盖、备份和数据卷。
两端的原生解释器路径分别记录在部署目录的 `.python` 中；WSL 的独立控制器运行时可放在
`/opt/dev-infra/host/`，部署会保留它。`dev-infra self status` 显示实际 Python 版本和路径。
WSL 解释器不在 PATH 时，首次 Windows 安装使用
`.\scripts\install.ps1 -WslPython <WSL中的Python3.14路径>`。

只安装 WSL 入口：

```bash
sudo bash scripts/install.sh
```

也可显式指定 WSL 原生解释器：

```bash
sudo DEV_INFRA_PYTHON=/path/to/python3.14 bash scripts/install.sh
```

## 日常命令

```text
dev-infra                         # 默认显示 list
dev-infra list
dev-infra show mysql              # 详情与连接信息，密码默认隐藏
dev-infra show mysql --secrets     # 显示连接密码
dev-infra show s3 --open           # 打开网页
dev-infra start                   # 默认全部服务
dev-infra start core
dev-infra stop kafka
dev-infra restart postgres
dev-infra remove mailpit          # 删除容器，保留数据
dev-infra logs kafka -f
dev-infra check                   # 只读检查环境与配置
dev-infra check --updates         # 只读检查兼容分支的新版本
dev-infra help upgrade
```

服务：`mysql postgres redis kafka s3 mailpit`。分组：`core`（前四项）、`extra`（后两项）、`all`。
Windows 命令自动使用共享 WSL 后端；在 WSL 管理 `/opt` 中的实例通常使用 `sudo`。
查询、升级预览和帮助不创建配置、不拉取镜像、不启动容器。
查询和操作结果支持 `--json`，日志与 Compose 原始输出除外。

## 中间件升级

```text
dev-infra check --updates
dev-infra upgrade --dry-run
dev-infra upgrade                 # 升级全部服务的兼容分支
dev-infra upgrade redis           # 升级一个服务
dev-infra upgrade postgres --to 18.6 --dry-run
dev-infra upgrade postgres --to 18.6
dev-infra upgrade --no-backup      # 本次明确跳过数据库备份
```

`upgrade` 自动解析最新稳定版本，固定标签也会升级，无需先改仓库 `versions.env`。
流程为校验、数据库备份、拉取全部目标镜像、保存版本、重建受影响的服务、健康验证。
结果以明确版本和 SHA256 摘要写入本机 `versions.local.env`，工具部署会保留该文件。
升级 RustFS 时包含配套客户端。

MySQL 限当前 LTS 分支、Kafka 限当前次版本；PostgreSQL、Redis、RustFS、Mailpit 限当前主版本。
跨出这些范围会显示迁移要求并停止操作，不直接复用旧卷。具体迁移、新卷切换和失败恢复见
[中间件升级与迁移](docs/upgrades.md)。

## 配置与数据

```text
dev-infra config                  # 本机偏好与默认值
dev-infra config edit
dev-infra config check
dev-infra config edit --instance  # 端口、账号和数据卷
dev-infra config show --versions  # 查看已升级的本机版本
dev-infra data                    # 数据卷、大小和容器引用
dev-infra data backup mysql
dev-infra data reset redis --dry-run
dev-infra data reset redis --yes
dev-infra data prune --dry-run
dev-infra data prune --yes        # 仅清理本实例的未引用旧卷
```

偏好位于 Windows `%USERPROFILE%\.config\dev-infra\config.toml` 或 WSL 调用用户的
`~/.config/dev-infra/config.toml`。默认中文，通过 `language = "en"` 切换英文。
编辑器依次使用配置 argv、VISUAL、EDITOR，最后 Windows Notepad / WSL vi。
`operation.backup = false` 可关闭升级的默认备份，命令行 `--backup` / `--no-backup` 覆盖本次策略。
默认备份为 true；数据库未运行时无法备份，需先启动或明确跳过。

实例 `.env`、版本覆盖 `versions.local.env`、操作记录 `.state/`、备份 `backup/` 和数据卷
留在本机。默认开发账号见 `.env.example`；`show --secrets` 查看当前声明中的连接信息。
修改 `.env` 密码不会修改已有数据库账号，需在数据库中同步修改。完整字段见[配置说明](docs/config.md)。

## 工具更新

先在源码仓库拉取代码，再部署工具自身：

```text
git pull --ff-only
dev-infra self update
dev-infra self status
```

源码位置不可用时使用 `dev-infra self update --source <仓库目录>`。Windows 更新同时部署
Windows 控制程序和 WSL 后端；WSL 更新只部署后端。此操作保留实例数据，并不会升级中间件。

## 开发与验证

源码按命令、服务目录、偏好、实例声明、升级计划、Docker 适配、数据操作和展示分层。
检查命令和升级执行共用计划，变更操作使用本实例的互斥锁。

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m unittest discover -v tests
uvx ruff check src scripts/dev-infra.py tests
uvx ruff format --check src scripts/dev-infra.py tests
```

WSL 使用 `PYTHONPATH="$PWD/src" python3.14 -m unittest discover -v tests`。
真实生命周期验证：`python3.14 tests/integration/lifecycle.py`，使用已安装 Redis 镜像、隔离的
Compose 项目和临时卷，无宿主端口，结束后清理。详见[开发说明](docs/development.md)。

## 卸载

```powershell
.\scripts\uninstall.ps1
```

仅移除命令入口和用户 PATH 项，保留程序文件、偏好、实例配置、备份及 Docker 数据卷。

## 许可证

本项目采用 [MIT 许可证](LICENSE)。
