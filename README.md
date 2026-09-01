# dev-infra

`dev-infra` 是一套供 Windows 与 WSL 共用的本地开发中间件环境。服务实际运行在 Docker
Desktop，配置与脚本安装在 WSL `/opt/dev-infra`，PowerShell 命令透明转发到同一个 WSL
实例，因此不会维护两套容器或数据。

## 服务

| 服务 | 用途 | 默认宿主端口 |
| --- | --- | ---: |
| MySQL 8.4 | 关系型数据库 | `23306` |
| PostgreSQL 17 | 关系型数据库 | `25432` |
| Redis 8 | 缓存与键值存储 | `26379` |
| Kafka | 事件流与消息平台 | `29092` |
| RustFS | S3 兼容对象存储 | `28333` / `28346` |
| Mailpit | 开发邮件捕获与查看 | `21025` / `28025` |

所有宿主端口只绑定到 `127.0.0.1`。容器内部仍使用各产品的标准端口。数据保存在独立的
Docker named volume 中，重建或删除容器不会删除数据卷。

## 环境要求

- Windows 11 与 WSL 2 Ubuntu。
- Docker Desktop，并为 Ubuntu 启用 WSL Integration。
- WSL 中提供 Bash、`rsync` 和 Docker Desktop 挂载的 Docker CLI。

## 安装

从 PowerShell 克隆私仓并安装：

```powershell
git clone git@github.com:hhhxxxddd/dev-infra.git
cd dev-infra
.\scripts\install.ps1
```

安装器会：

1. 将可移植代码同步到 WSL `/opt/dev-infra`。
2. 首次安装时从 `.env.example` 创建本机 `.env`。
3. 创建 WSL `/usr/local/bin/dev-infra`。
4. 在 PowerShell Profile 中创建同名转发命令。

重新运行安装器即可更新已安装代码。更新过程不会覆盖 `/opt/dev-infra/.env`、
`/opt/dev-infra/backup` 或 Docker named volume。

也可以从 WSL 安装：

```bash
sudo bash scripts/install.sh
```

## 常用命令

Windows PowerShell 与 WSL 使用完全相同的命令：

```bash
dev-infra                         # 状态面板
dev-infra help                    # 中文帮助
dev-infra list                    # 服务、用途、状态和地址
dev-infra info mysql              # MySQL 连接信息
dev-infra info all                # 全部连接信息

dev-infra start                   # 启动全部服务
dev-infra start core              # 启动四个核心服务
dev-infra start extra             # 启动 RustFS 和 Mailpit
dev-infra start mysql redis       # 启动指定服务
dev-infra start --pull all        # 拉取镜像后启动

dev-infra stop kafka
dev-infra restart postgres
dev-infra remove all              # 删除容器，保留数据卷
dev-infra logs kafka -f

dev-infra update redis
dev-infra backup all
dev-infra reset redis --yes        # 删除 Redis 数据卷并重建
dev-infra doctor
dev-infra open s3
dev-infra open mailpit
```

支持的服务名：`mysql postgres redis kafka s3 mailpit`。

支持的分组：

- `core`：MySQL、PostgreSQL、Redis、Kafka。
- `extra`：RustFS、Mailpit。
- `all`：全部服务，也是 `start/stop/restart/remove/status/info` 的默认范围。

## 默认连接信息

```text
MySQL       dev / dev123456 @ 127.0.0.1:23306/dev
MySQL root  root / root123456
PostgreSQL  dev / dev123456 @ 127.0.0.1:25432/dev
Redis       无密码 @ 127.0.0.1:26379
Kafka       PLAINTEXT @ 127.0.0.1:29092
S3          dev / dev123456 @ http://127.0.0.1:28333，Bucket: dev
S3 Console  http://127.0.0.1:28346/rustfs/console/index.html
Mailpit     SMTP 无认证 @ 127.0.0.1:21025
Mailpit UI  http://127.0.0.1:28025
```

运行 `dev-infra info [服务]` 可以随时读取当前 `.env` 对应的真实连接信息。

## 配置与数据边界

仓库保存：

- Compose、服务配置模板和初始化脚本。
- `.env.example` 与镜像版本声明。
- Windows/WSL 安装器和 CLI 实现。

本机保留且不提交：

- `/opt/dev-infra/.env`：端口、开发账号和本机覆盖设置。
- `/opt/dev-infra/backup`：数据库备份。
- Docker named volume：数据库和中间件数据。

修改 `.env` 或 Compose 后运行 `dev-infra restart [服务]`。修改数据库密码不会自动修改已有
数据卷中的账号；应在数据库内修改，或在数据可丢弃时运行 `reset`。

## 卸载入口

从 PowerShell 执行：

```powershell
.\scripts\uninstall.ps1
```

卸载器只移除 Windows 与 WSL 命令入口，不删除 `/opt/dev-infra`、备份或 Docker 数据。
