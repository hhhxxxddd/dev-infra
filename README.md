# dev-infra

**简体中文** · [English](README.en.md)

[![License MIT](https://img.shields.io/badge/License-MIT-blue)](LICENSE) [![WSL Ubuntu](https://img.shields.io/badge/WSL-Ubuntu-brightgreen)](docs/config.md) [![Python 3.14](https://img.shields.io/badge/Python-3.14-blue)](docs/config.md)

提供开箱即用的本地开发中间件，通过 Windows/WSL 共用的 WSL Docker Compose 后端查询连接、启停服务、升级镜像和管理数据。

## 环境要求

| 平台 / 依赖 | 版本或要求 | 用途 / 范围 |
| --- | --- | --- |
| Windows | Windows 11 | Windows 入口；仅使用 WSL 时不需要 |
| PowerShell | 7 或更新版本 | Windows 安装与命令入口 |
| WSL / Ubuntu | WSL 2；已验证 Ubuntu 24.04 LTS | 共享后端 |
| Python | 3.14.x | 两端已有原生外部解释器；安装器不自动安装或升级 |
| Docker | Docker + Compose v2 | WSL 后端；Docker Desktop 需启用 WSL Integration |
| Git | `git` 命令可用 | Git 源码安装与更新 |
| rsync / flock | WSL 中可用 | 文件部署与操作锁 |

## 安装

### Scoop（Windows）

通过 hxd-box 安装正式发行版：

```powershell
scoop bucket add hxd-box https://github.com/hhhxxxddd/hxd-box
scoop install hxd-box/dev-infra
```

Scoop 自动安装 PowerShell；两端的 Python 和 WSL 后端依赖需提前准备。

### Git（Windows）

```powershell
git clone https://github.com/hhhxxxddd/dev-infra.git
cd dev-infra
.\scripts\install.ps1
```

安装后在新终端使用 `dev-infra`，Windows 操作自动转发到 WSL 后端。
仅使用 WSL、指定外部解释器或卸载时，见[完整安装说明](docs/config.md#安装与工具维护)。

## 快速开始

```text
dev-infra check
dev-infra start core
dev-infra list
dev-infra show mysql
```

`core` 包含 MySQL、PostgreSQL、Redis、Kafka；`extra` 包含 RustFS、Mailpit。
原生 WSL 管理 `/opt` 中的实例通常需要 `sudo`。

## 常用命令

| 命令 | 用途 |
| --- | --- |
| `dev-infra upgrade` | 升级中间件 |
| `dev-infra self upgrade` | 升级 dev-infra 自身 |
| `dev-infra config edit --instance` | 编辑实例配置 |
| `dev-infra data list` | 查看数据卷与容器引用 |
| `dev-infra -v` / `dev-infra help` | 查看版本或帮助；不带参数也显示帮助 |

删除容器会保留 Docker 数据卷；显式数据清理才会删除数据。
工具安装与更新保留本机配置、外部 Python 和实例数据，不重启中间件。

默认中文，在用户 `config.toml` 设置 `language = "en"` 切换英文。
语言与编辑器等用户偏好和实例配置分开保存，详见[配置说明](docs/config.md)。

## 文档

[配置与安装](docs/config.md) · [升级与迁移](docs/upgrades.md) · [接口约定](docs/cli-contract.md)

[发行与更新](docs/releases.md) · [开发与贡献](docs/development.md)
