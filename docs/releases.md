# 发行包与工具更新

[English](releases.en.md) · [配置与安装](config.md)

## 完整发行包

dev-infra 自行构建发行包，不依赖 dev-tools 仓库或模块。ZIP 包含控制程序、Windows/WSL
入口、安装与卸载脚本、Compose、默认版本、实例模板、config/init、双语文档和 MIT 许可。
本机 `.python`、`.source`、`.env`、`versions.local.env`、状态、备份、私有宿主和缓存不会打包。

在原生 Python 3.14 下构建候选包，可以保留未提交修改：

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m dev_infra.release --output dist
python -m dev_infra.package_smoke dist/dev-infra-0.3.0.zip
```

构建生成 `dev-infra-<版本>.zip`、`SHA256SUMS` 和 Scoop 使用的 `dev-infra.json`。
文件名来自统一版本声明；ZIP 使用固定排序、时间、LF 换行和无压缩存储，以便 Windows 与
Linux 构建相同字节。包内 `.release.json` 使用 schema_version=1，记录仓库、版本、Git
commit、dirty 标识和逐文件 SHA256。dirty 候选不能作为正式发行。

正式构建必须来自官方 origin 的干净检出目录，HEAD 与对应版本 tag 一致，并具有版本说明：

```powershell
python -m dev_infra.release --tag v0.3.0 --official --output dist
```

该命令不创建 tag、不发布 Release，也不推送 bucket。版本说明在
[docs/releases/v0.3.0.md](releases/v0.3.0.md)；发布时本地文档链接转换为对应 commit 的 GitHub 链接。
Scoop 清单作为正式 Release 附件生成，由 [hxd-box](https://github.com/hhhxxxddd/hxd-box)
同步维护；本仓库的发行工作流不自动推送 bucket。

## 校验与安装

仅从[官方 GitHub Releases](https://github.com/hhhxxxddd/dev-infra/releases)获取 ZIP 和
`SHA256SUMS`，先验证 ZIP 的 SHA256，再解压。离线 `package_smoke` 同时校验 ZIP 和包内
逐文件清单，通过临时外部 Python 绑定运行实际原生入口的版本、帮助和配置查询，不访问 Docker
或安装到全局目录。重复安装与数据保留另由隔离安装测试验证。

解压后执行：

```powershell
.\scripts\install.ps1
```

仅部署 WSL 时执行：

```bash
sudo DEV_INFRA_PYTHON=/path/to/python3.14 bash scripts/install.sh
```

两端需要已有的原生 Python 3.14，WSL 仍需要 rsync、flock、Docker CLI；发行包安装不要求
Git 检出目录。部署复用已有解释器绑定，保留实例配置、镜像版本覆盖、状态和备份，不重启中间件。

SHA256 和 receipt 证明内容完整性，不能充当发布者签名。receipt 中的仓库或 commit 字段本身
不证明身份；本地包须由使用者确认来自官方渠道，并对照同一官方渠道的校验值。自动下载固定使用
官方仓库的稳定 Release API、ZIP 与校验文件，拒绝不匹配的版本、摘要和非法路径。

## 两种工具更新渠道

```text
dev-infra self status
dev-infra self upgrade
dev-infra self update
```

`self status` 的 channel 标识当前来源。Git 安装记录 `.source`，`self upgrade` 验证官方 origin，
要求工作区干净且分支跟踪 origin，获取源码后仅快进；分叉或本地修改不会被自动覆盖。
发行包安装保留 `.release.json`，不记录临时解压目录；`self upgrade` 下载并校验最新稳定 Release
后部署。Windows 部署两端，原生 WSL 只部署后端。Scoop 安装由 Scoop 更新。

`self update` 只重新部署当前代码，不 fetch 源码或下载新版。`--source <目录>` 可明确指定官方
Git 检出目录或已校验的解压包；显式指定的发行包直接部署。所有渠道均不升级 Python 或中间件，
本机偏好与实例数据保持独立。
