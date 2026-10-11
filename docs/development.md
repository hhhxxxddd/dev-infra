# 开发与验证

[English](development.en.md) · [返回 README](../README.md)

## 结构

```text
src/dev_infra/
  cli.py             命令目录、解析、前置校验、Windows 转发
  catalog.py         服务元数据、分组和兼容范围
  settings.py        用户偏好、编辑器与 sudo 身份
  instance.py        实例数据解析、原子写入与操作锁
  registry.py        Docker Hub 查询、稳定版本与分页
  planning.py        查询与执行共用的升级计划
  docker.py          Docker/Compose argv 与数据范围校验
  operations.py      生命周期、升级执行、重置与工具部署
  data.py            流式备份、卷归属与定向清理
  presentation.py    中文/英文目录及展示
scripts/             原生入口、安装与卸载
tests/               隔离控制层、备份、注册表与适配器检查
tests/integration/   独立 Docker 项目的真实生命周期验证
```

控制层只使用 Python 3.14 标准库，不兼容其他次版本。Compose 是唯一容器执行底座。
Windows 管本机偏好并转发操作；运行时、实例文件和操作锁在共享 WSL 后端。

## 检查

Windows：

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m unittest discover -v tests
uvx ruff check src scripts/dev-infra.py tests
uvx ruff format --check src scripts/dev-infra.py tests
```

WSL：

若使用部署目录中的独立解释器，先把它所在目录加入当前会话的 PATH：

```bash
export PATH="$(dirname "$(cat /opt/dev-infra/.python)"):$PATH"
```

```bash
export PYTHONPATH="$PWD/src"
python3.14 -m unittest discover -v tests
uvx ruff check src scripts/dev-infra.py tests
uvx ruff format --check src scripts/dev-infra.py tests
bash -n dev-infra
for file in scripts/*.sh; do bash -n "$file"; done
shellcheck dev-infra scripts/*.sh
```

bootstrap 测试前用 PowerShell Parser 解析每个 `scripts/*.ps1`。CI 使用 Linux/Windows，
Python 3.14，覆盖相同单元、格式和入口语法检查。测试不连接真实数据库或 Docker Hub。
备份测试运行真实流式压缩与失败清理路径，外部 dump 使用本地隔离进程。

## 真实生命周期

```bash
python3.14 tests/integration/lifecycle.py
```

要求 Docker 可用且声明的 Redis 镜像已安装。使用随机 Compose 项目名和临时卷，不暴露宿主
端口，不下载镜像。验证启动、健康、重建后的数据保留、删除容器保留卷、重置与自动清理。
部署后再验证 Windows `-NoProfile` 入口、WSL 入口、语言、JSON、只读升级预览与原有服务健康。

## 文档

两份 README 与两份配置/升级文档保持命令、默认值和示例一致。检查 Markdown 本地链接、
TOML 示例以及 Bash 迁移示例语法。安装时交付完整文档；模板保留中文指导。
