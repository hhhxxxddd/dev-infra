# CLI 与数据接口约定

[English](cli-contract.en.md) · [返回 README](../README.md)

## 输出与版本

`list`、`show`、`start`、`stop`、`restart`、`remove`、`check`、`upgrade`、`config`、`data`、`self`
支持 `--json`。每次调用的 stdout 只有一个 UTF-8 JSON 对象，包括参数错误、无效配置、执行失败和
中断；控制器日志、编辑器及安装过程的输出走 stderr。`logs`、`compose` 保留原始输出；帮助和
版本选项输出文本。`--json` 必须出现在参数分隔符 `--` 之前。

`compose` 透传的已知只读命令不初始化实例；变更和未知命令共用实例操作锁，包括 `config --output` 和 `wait --down-project`。

每个 JSON 结果带整数 `schema_version = 1`，由公开接口版本常量控制，与工具版本及内部状态格式
版本独立。现有业务字段保持在顶层，不增加统一的 `data` 包装。新增字段允许客户端忽略；删除、
改名或改变已有字段类型需要提升接口版本。数组顺序用于展示，不应代替 `service` / `volume`
标识来关联记录。客户端应处理未知状态值，不解析本地化文字。

失败包含 `error` 对象，必有字符串 `code`、字符串 `message`、对象 `details`。`code`、JSON 键
和状态标识不随语言变化；`message` 可按偏好语言翻译，不用于程序判断。`details` 为诊断数据，
可能包含 `detail` 字符串；它不是可执行代码。错误诊断会隐藏已知凭据和 SQL，成功的 `show`
默认隐藏密码，只有显式 `--secrets` 才输出连接密码。

```json
{
  "schema_version": 1,
  "complete": false,
  "state": "error",
  "error": {
    "code": "unknown_service",
    "message": "未知服务或分组",
    "details": {"detail": "example"}
  }
}
```

部分结果和升级阻断保留业务记录，并增加顶层 `error`。`complete` 表示本次查询或操作完成情况，
不等于所有服务健康：`list` 查询成功时，仍可能列出 `exited` 或 `unhealthy`；`check --updates`
发现可更新版本也可成功返回。应同时检查服务状态、`blocked` 和诊断项。

## 退出码

| 退出码 | 约定 |
| --- | --- |
| `0` | 查询或操作成功；发现可更新版本、普通无变化操作仍为成功 |
| `1` | 执行失败、查询不完整、部分备份未完成、升级阻断或缺少删除确认 |
| `2` | 参数语法或语义错误，包括未知服务、非法目标版本、服务数量和选项组合 |
| `130` | 用户中断 |

无效 TOML / 实例配置和未知内部状态格式属于环境或记录错误，返回 `1`。Windows 转发保持这些
退出码；后端未返回受支持的单一 JSON 对象时输出 `transport_failed`，返回 `1`。

## 业务结果

| 命令 | 主要字段与类型 |
| --- | --- |
| `list` / `show` / 生命周期 | `complete: boolean`、`services: object[]`；每项含字符串 `service/state/image/endpoint/volume`；show 增加连接详情 |
| `check` | `complete: boolean`、`checks: object[]`、`recovery: object`；检查项含字符串 `check/state`，可有 `detail` |
| `check --updates` / `upgrade` | `complete/blocked/backup: boolean`、`services_selected: string[]`、`images: object[]`、`steps: string[]`；查询带 `mode: "check"` |
| `data list` / `prune` | `complete: boolean`、`volumes: object[]`；prune 可有 `removed: string[]` |
| `data backup` | `complete: boolean`、`backups: object[]`；每项含 `service/state`，成功时有 `path` |
| `data reset` | 字符串 `action/service/volume/state`、`users/steps: string[]` |
| `config` | 字符串 `path/state`、`exists: boolean`、`values: object` |
| `self status` | `controller_version/python_version/python_executable/root/source/distro` 字符串 |
| `self update` / `upgrade` | 字符串 `state`；可有字符串 `channel/source` 和来源诊断 |

镜像项含字符串 `service/state/image/target`；成功解析的目标另有字符串 `version/version_key`、
布尔值 `change` 和可为 null 的 `reason`。单项查询失败保留 `state: "error"` 和诊断字符串
`error`；顶层错误码表示整体失败。`instance_signature` 是防止配置变化的内部校验数据，不应
修改或作为可直接执行的升级计划提交。

当前核心状态如下；Docker 原生状态会按实际值透传。

| 对象 | 状态 / 标识 |
| --- | --- |
| 服务 | `not_created/unavailable`，以及 Docker 的 `healthy/unhealthy/starting/running/created/exited/paused/restarting/removing/dead` |
| 镜像 | `current/update_available/not_downloaded/blocked/error` |
| 检查项 | `ok/error/skipped/warning` |
| 数据卷 `state` | `active/referenced/obsolete/external` |
| 数据卷 `ownership` | `managed/external` |
| 备份 | `complete/skipped/error` |
| 恢复诊断 | `none/running/error/complete/unchanged/invalid` |
| 升级逐服务进度 | `pending/pulling/pulled/applying/complete/error` |

卷项另含字符串 `service/volume/size/mountpoint` 和 `users: string[]`。`managed` 必须由当前实例
匹配的 Docker 标签证明；名称、历史 ledger 和字段本身均不构成删除授权。清理时重新检查标签、
当前配置和全部容器引用。`reset --yes` 是显式销毁所选当前卷；`prune --yes` 仅清理已证明归属的
闲置旧卷。先用 `data list` 查看，查询不会创建配置、卷、镜像、容器、备份或修复记录。

## 配置字段

配置层保持独立：原生用户 `config.toml` 管偏好，WSL 实例 `.env` 管端口/账号/卷，
`versions.local.env` 管本机镜像版本覆盖。Windows 不把自己的偏好文件路径传给 WSL。

| 偏好字段 | 类型与默认值 |
| --- | --- |
| `language` | `"zh"`（默认）或 `"en"` |
| `editor` | 字符串 argv 数组，默认 `[]`，使用现有编辑器回退 |
| `wsl.distro` | 非空字符串，默认 `"Ubuntu"` |
| `operation.wait_timeout` | 整数 `1–3600`，默认 `240` |
| `operation.backup` | 布尔值，默认 `true` |

未知字段和错误类型拒绝读取；缺失字段补默认值，查询不会写回。实例端口必须是 `1–65535` 且
不重复，卷名必须合法且不重复；版本覆盖仅接受版本目录中的已知键和稳定版本格式。字段详见
[配置文档](config.md)。

## 恢复记录与备份边界

`check --json` 的 `recovery` 必含 `state`、`needs_attention: boolean`、`journal: string`、
`automatic_rollback: false` 和 `recommendations: object[]`。有历史记录时可含失败 `stage`、
`active_service`、时间戳、`error`、`completed_steps: string[]`、`backups: object[]` 和
`services: object[]`。时间戳为带时区的 ISO 8601 UTC 字符串，未完成时间可为 null。历史诊断
错误含 `type/code/message`；`recommendations` 中的 `action` 是稳定标识，`argv` 是参数数组，
只展示建议，查询不会执行它们。失败重试会重新校验；不会自动回滚数据库。

`.state/last-upgrade.json` 和 `.state/volumes.json` 使用独立 `format_version = 1`：

```json
{"format": "dev-infra.state", "format_version": 1, "payload": {}}
```

`payload` 保留原升级记录或卷引用映射。已有未版本化本机记录可安全读取，读取时不迁移、不丢失
引用。下一次合法操作写入当前格式。未知版本或损坏记录返回诊断，原文件保持原样，升级不会覆盖
未知日志，清理不会依据异常 ledger 删除卷；需要先检查文件后再显式修复。原子写入和实例操作锁
继续保护正常更新。

备份为 SQL gzip 文件，成功记录包含路径，失败不会发布不完整文件。它不是数据库原始卷快照；
该接口没有自动恢复、自动迁移或自动回滚承诺。恢复前应核对数据库版本、扩展/插件、账号权限和
目标配置，再使用数据库工具显式导入并验证数据。已完成的备份和失败阶段会保留在升级诊断中。
步骤及跨版本迁移见[升级文档](upgrades.md)。
