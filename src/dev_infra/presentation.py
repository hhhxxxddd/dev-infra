"""Central Chinese/English controller messages; JSON identifiers stay stable."""

import json
import unicodedata

TEXT = {
    "title": ("Windows / WSL 共用的本地中间件管理", "Shared local middleware for Windows / WSL"),
    "list": ("查看服务概览（默认命令）", "List services (default command)"),
    "show": ("查看详情和连接信息", "Show details and connections"),
    "start": ("启动服务", "Start services"),
    "stop": ("停止服务", "Stop services"),
    "restart": ("重建并重启服务", "Recreate and restart services"),
    "remove": ("删除容器，保留数据", "Remove containers, retain data"),
    "logs": ("查看日志", "Read logs"),
    "check": ("检查环境；--updates 检查更新", "Check environment; --updates checks releases"),
    "upgrade": ("升级中间件；--dry-run 预览", "Upgrade middleware; --dry-run previews the plan"),
    "config": ("查看、编辑、检查配置", "Show, edit or validate configuration"),
    "data": ("查看数据卷、备份、重置或清理", "Inspect volumes, back up, reset or prune"),
    "self": ("查看或更新工具自身", "Inspect or update the controller"),
    "compose": ("直接调用本实例 Compose", "Call this instance's Compose directly"),
    "help": ("查看命令帮助", "Show command help"),
    "command": ("命令", "command"),
    "action": ("操作", "action"),
    "path": ("路径", "Path"),
    "root": ("程序目录", "Program directory"),
    "source": ("源码目录", "Source checkout"),
    "controller_version": ("工具版本", "Controller version"),
    "python_version": ("Python 版本", "Python version"),
    "python_executable": ("Python 路径", "Python executable"),
    "python_required": ("需要 Python 3.14", "Python 3.14 is required"),
    "distro": ("WSL 发行版", "WSL distribution"),
    "yes": ("是", "Yes"),
    "no": ("否", "No"),
    "connection": ("连接", "Connection"),
    "root_password": ("root 密码", "Root password"),
    "web": ("网页", "Web page"),
    "access_key": ("访问标识", "Access key"),
    "secret_key": ("访问密钥", "Secret key"),
    "bucket": ("存储桶", "Bucket"),
    "region": ("区域", "Region"),
    "check_item": ("检查项", "Check"),
    "docker": ("Docker 连接", "Docker connection"),
    "mysql_config_permissions": ("MySQL 配置权限", "MySQL configuration permissions"),
    "port_declarations": ("端口声明", "Port declarations"),
    "steps": ("步骤", "Steps"),
    "validate": ("校验", "Validate"),
    "backup": ("备份", "Back up"),
    "skip_backup": ("跳过备份", "Skip backups"),
    "pull": ("拉取镜像", "Pull images"),
    "save_versions": ("保存版本", "Save versions"),
    "recreate": ("重建服务", "Recreate services"),
    "healthcheck": ("健康验证", "Health check"),
    "remove_container": ("删除容器", "Remove container"),
    "delete_volume": ("删除数据卷", "Delete volume"),
    "create_volume": ("创建数据卷", "Create volume"),
    "removed": ("已删除", "Removed"),
    "incompatible_options": (
        "这些选项不能用于此操作",
        "These options cannot be used with this action",
    ),
    "web_unavailable": ("请指定 s3 或 mailpit 打开网页", "Select s3 or mailpit to open a web page"),
    "root_required": ("请通过 sudo 执行", "Run with sudo"),
    "install_failed": ("安装失败", "Installation failed"),
    "plan_changed": (
        "配置在生成计划后发生变化，请重新执行",
        "Configuration changed after planning; rerun the command",
    ),
    "services_arg": (
        "服务或分组：mysql postgres redis kafka s3 mailpit；core extra all",
        "Services: mysql postgres redis kafka s3 mailpit; groups: core extra all",
    ),
    "json_arg": ("以 JSON 输出", "Output JSON"),
    "dry_arg": (
        "只预览，不修改配置、镜像或数据",
        "Preview without changing configuration, images or data",
    ),
    "to_arg": ("单个服务的目标稳定版本", "Target stable version for one service"),
    "no_backup_arg": ("本次升级跳过数据库备份", "Skip database backups for this upgrade"),
    "backup_arg": ("本次升级强制备份数据库", "Back up databases for this upgrade"),
    "updates_arg": (
        "只读检查兼容分支的新版本",
        "Read-only release checks within compatible branches",
    ),
    "secrets_arg": ("显示连接密码", "Show connection passwords"),
    "open_arg": ("打开此服务的网页", "Open this service's web page"),
    "follow_arg": ("持续跟踪日志", "Follow logs"),
    "tail_arg": ("显示最近行数，默认 200", "Recent lines, default 200"),
    "instance_arg": ("端口、账号等实例配置", "Instance settings: ports and accounts"),
    "versions_arg": ("本机镜像版本覆盖", "Local image version overrides"),
    "yes_arg": ("确认删除数据", "Confirm data deletion"),
    "source_arg": ("已拉取新代码的可信仓库目录", "Verified checkout containing the new code"),
    "preferences_arg": ("使用指定偏好文件", "Use a specific preferences file"),
    "version_arg": ("显示工具版本", "Show the controller version"),
    "config_actions": ("show 查看（默认）；edit 编辑；check 校验", "show (default), edit, check"),
    "data_actions": (
        "list 查看（默认）；prune 清理旧卷；backup 备份；reset 重置单个服务",
        "list (default), prune obsolete volumes, backup databases, reset one service",
    ),
    "self_actions": (
        "status 查看（默认）；update 从已更新的源码部署",
        "status (default), update from an updated checkout",
    ),
    "backup_unavailable": (
        "数据库未运行，无法完成备份；请先启动，或显式使用 --no-backup",
        "Database is not running; start it before backup, or explicitly use --no-backup",
    ),
    "usage": ("用法", "usage"),
    "options": ("选项", "options"),
    "positionals": ("位置参数", "positional arguments"),
    "arg_error": ("参数错误", "Argument error"),
    "unknown_service": ("未知服务或分组", "Unknown service or group"),
    "invalid_config": ("偏好配置无效", "Invalid preferences"),
    "invalid_env": ("实例配置无效", "Invalid instance configuration"),
    "invalid_version": (
        "请输入稳定版本，例如 18.6 或 v1.31.4",
        "Use a stable version such as 18.6 or v1.31.4",
    ),
    "invalid_registry": ("镜像仓库返回了无效元数据", "Invalid registry metadata"),
    "incomplete_registry": (
        "镜像标签分页超出限制，查询不完整",
        "Registry pagination limit exceeded",
    ),
    "no_release": ("没有找到兼容分支的稳定版本", "No stable release in the compatible branch"),
    "docker_failed": ("Docker 操作失败", "Docker operation failed"),
    "docker_unavailable": (
        "Docker 不可用，请启动 Docker Desktop 并启用 WSL 集成",
        "Docker unavailable; start Docker Desktop and enable WSL integration",
    ),
    "editor_failed": ("编辑器退出失败", "Editor failed"),
    "busy": ("另一项中间件操作正在执行", "Another middleware operation is in progress"),
    "one_target": ("此操作需要指定一个服务", "This operation requires exactly one service"),
    "db_only": ("备份支持 mysql 和 postgres", "Backups support mysql and postgres"),
    "confirm_required": (
        "请添加 --yes 确认删除数据；可先用 --dry-run 预览",
        "Add --yes to delete data; preview with --dry-run first",
    ),
    "volume_busy": ("数据卷仍被容器引用", "Volume is still referenced by a container"),
    "migration_required": (
        "此版本变更需要迁移，请参阅 docs/upgrades.md；未执行升级",
        "This version change requires migration; see docs/upgrades.en.md; upgrade not executed",
    ),
    "downgrade_blocked": (
        "不支持直接降级，或无法确认目标高于当前版本",
        "Direct downgrades or unverified upgrade directions are not supported",
    ),
    "query_failed": ("更新查询失败", "Release query failed"),
    "upgrade_failed": (
        "升级未完成；保留目标声明和已完成步骤，修复后重新执行 upgrade",
        "Upgrade incomplete; target declarations and completed steps are retained; fix the cause and rerun upgrade",
    ),
    "unverified_source": ("仓库来源未经验证", "Unverified checkout origin"),
    "source_missing": (
        "找不到源码目录，请用 --source 指定已拉取新代码的仓库",
        "Source unavailable; use --source to select an updated checkout",
    ),
    "service": ("服务", "Service"),
    "state": ("状态", "State"),
    "image": ("镜像", "Image"),
    "endpoint": ("地址", "Endpoint"),
    "volume": ("数据卷", "Volume"),
    "target": ("目标", "Target"),
    "size": ("大小", "Size"),
    "users": ("引用容器", "Containers"),
    "current": ("最新", "Current"),
    "update_available": ("可升级", "Upgrade available"),
    "not_created": ("未创建", "Not created"),
    "not_downloaded": ("未下载", "Not downloaded"),
    "unavailable": ("不可用", "Unavailable"),
    "healthy": ("健康", "Healthy"),
    "unhealthy": ("不健康", "Unhealthy"),
    "starting": ("启动中", "Starting"),
    "running": ("运行中", "Running"),
    "exited": ("已停止", "Stopped"),
    "created": ("已创建", "Created"),
    "error": ("失败", "Error"),
    "active": ("当前使用", "Active"),
    "referenced": ("仍被引用", "Referenced"),
    "obsolete": ("可清理", "Obsolete"),
    "ok": ("正常", "OK"),
    "complete": ("完成", "Complete"),
    "skipped": ("已跳过", "Skipped"),
    "blocked": ("需要迁移", "Blocked"),
    "unchanged": ("无需变更", "Unchanged"),
    "mysql_description": ("MySQL 关系型数据库", "MySQL relational database"),
    "postgres_description": ("PostgreSQL 关系型数据库", "PostgreSQL relational database"),
    "redis_description": ("Redis 缓存与键值存储", "Redis cache and key-value store"),
    "kafka_description": ("Kafka 事件流与消息平台", "Kafka event streaming"),
    "s3_description": ("RustFS 对象存储", "RustFS object storage"),
    "mailpit_description": ("Mailpit 邮件捕获", "Mailpit mail capture"),
}


class Presentation:
    def __init__(self, language: str):
        self.language = language

    def t(self, key: str) -> str:
        return TEXT[key][self.language == "en"] if key in TEXT else key

    def error(self, error: Exception) -> str:
        key, _, detail = str(error).partition("|")
        return self.t(key) + (f"：{detail}" if detail else "")

    def output(self, payload: dict, as_json: bool) -> None:
        if as_json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return
        if "services" in payload:
            self.table(payload["services"], ("service", "state", "image", "endpoint"))
            if payload.get("details"):
                for record in payload["services"]:
                    print(f"\n{record['service']}")
                    for key in (
                        "volume",
                        "connection",
                        "root_password",
                        "web",
                        "access_key",
                        "secret_key",
                        "bucket",
                        "region",
                    ):
                        if key in record:
                            print(f"  {self.t(key)}: {record[key]}")
        elif "images" in payload:
            if payload.get("state"):
                print(f"{self.t('state')}: {self.t(payload['state'])}")
            self.table(payload["images"], ("service", "state", "image", "target"))
            if payload.get("mode") != "check":
                print(
                    f"{self.t('steps')}: " + " → ".join(self.t(step) for step in payload["steps"])
                )
            for record in payload["images"]:
                if record.get("reason"):
                    print(self.t(record["reason"]))
                if record.get("error"):
                    print(self.error(ValueError(record["error"])))
        elif "volumes" in payload:
            self.table(payload["volumes"], ("service", "state", "volume", "size", "users"))
            if payload.get("removed"):
                print(self.t("removed") + ": " + ", ".join(payload["removed"]))
        elif "checks" in payload:
            self.table(payload["checks"], ("check", "state"))
            for record in payload["checks"]:
                if record.get("detail"):
                    print(f"{self.t(record['check'])}: {self.error(ValueError(record['detail']))}")
        elif "backups" in payload:
            self.table(payload["backups"], ("service", "state", "path"))
        else:
            for key, value in payload.items():
                if key == "steps":
                    value = " → ".join(self.t(v) for v in value)
                elif isinstance(value, bool):
                    value = self.t("yes" if value else "no")
                elif isinstance(value, list):
                    value = ", ".join(str(v) for v in value) or "-"
                elif key in ("state", "action"):
                    value = self.t(str(value))
                print(f"{self.t(key)}: {value}")

    def table(self, records: list[dict], keys: tuple[str, ...]) -> None:
        def width(value):
            return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in value)

        rows = [[self.t("check_item" if k == "check" else k) for k in keys]]
        for record in records:
            row = []
            for key in keys:
                value = record.get(key, "-")
                if isinstance(value, list):
                    value = ", ".join(value) or "-"
                row.append(self.t(str(value)) if key in ("state", "check") else str(value))
            rows.append(row)
        widths = [max(width(row[i]) for row in rows) for i in range(len(keys))]
        for row in rows:
            print(
                "  ".join(
                    value + " " * (size - width(value)) for value, size in zip(row, widths)
                ).rstrip()
            )
