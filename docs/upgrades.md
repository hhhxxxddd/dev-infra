# 中间件升级与迁移

[English](upgrades.en.md) · [返回 README](../README.md)

## 常规升级

```text
dev-infra check --updates
dev-infra upgrade
dev-infra upgrade redis
dev-infra check --updates postgres --to 18.6
dev-infra upgrade postgres --to 18.6
dev-infra check --updates --no-backup
dev-infra upgrade --no-backup
```

`check --updates` 只读显示版本、兼容范围、备份策略和执行步骤，不拉取镜像或修改实例。
它与 `upgrade` 共用计划；查询失败时保留其他结果，执行要求全部查询成功且没有迁移阻断。
`--to`、`--backup` 和 `--no-backup` 在 check 中必须与 `--updates` 同用；`--json` 只控制输出格式。
自动升级范围如下，RC、preview、edge 不参与选择：

| 服务 | 自动范围 | 跨范围方法 |
| --- | --- | --- |
| MySQL | 当前 LTS 分支，例如 8.4 | 升级检查、账号兼容调整，按官方路径迁移到新卷 |
| PostgreSQL | 当前主版本，例如 18 | 新集群逻辑导入或 pg_upgrade，验收后切换新卷 |
| Redis | 当前主版本，例如 8 | 校验 RDB/AOF 和模块兼容，迁入新卷；缓存可选择重置 |
| Kafka | 当前次版本，例如 4.3 | 按目标版本说明处理 KRaft/metadata.version，再切换声明 |
| RustFS | 当前主版本，例如 1 | 校验存储格式和发布说明，跨格式通过 S3 迁移到新卷 |
| Mailpit | 当前主版本，例如 v1 | 校验目标版本的 SQLite 数据兼容，迁入新卷或重置邮件 |
| RustFS 客户端 | 当前次版本，例如 v0.1 | 随 RustFS 一起更新；新次版本先验证命令与认证兼容 |

`--to` 指定一个服务的稳定版本或分支。程序解析其镜像摘要，保留兼容范围判断，不接受绕过迁移的
强制选项。已知降级会被拒绝；浮动标签无法证明升级方向时，使用该分支最新稳定版本。
具体版本与摘要保存到本机 `versions.local.env`，固定标签也可以被自动升级。

默认备份受影响的 MySQL/PostgreSQL。数据库未运行时停止升级，要求先启动数据库或明确使用
`--no-backup`。偏好 `operation.backup = false` 可改变默认策略。`data backup` 始终显式执行备份。

## 失败恢复

拉取全部目标镜像后才保存版本、重建容器。拉取失败时原有版本声明和容器不变。
`dev-infra check` / `check --json` 只读展示上次升级的失败阶段、错误、已完成步骤、逐服务状态和备份路径，并给出诊断、日志与重试命令。记录保存在 `/opt/dev-infra/.state/last-upgrade.json`；中途完成的备份也会立即记录。

先按建议修复环境、配置或启动问题，再执行同一 `upgrade` 命令。重跑重新校验当前状态和计划，不从旧记录盲目续跑。成功后旧错误会清除。数据库不自动换回旧镜像；数据格式升级后，镜像回退不等于数据回退。


## PostgreSQL 跨主版本

同主版本的小版本更新可以复用数据；跨主版本使用逻辑迁移或 pg_upgrade。
[官方说明](https://www.postgresql.org/docs/18/upgrading.html)。本项目 PostgreSQL 18 及以上将卷
挂到 `/var/lib/postgresql`，数据位于镜像默认的 `<主版本>/docker` 子目录。

下面给出逻辑直传方法，不生成 dump 备份文件。示例是 17→18；迁移其他主版本时将目标改成
已经发布并确认支持所用扩展的版本。先停止连接这个数据库的应用，保持应用停止直到切换验收完成。
在同一个有 Docker 权限、能读取 `/opt/dev-infra/.env` 的 WSL Bash 会话中执行。

准备目标；旧实例默认容器名为 `dev-postgres-1`：

```bash
set -Eeuo pipefail
old=dev-postgres-1
old_user=dev  # 换成当前 POSTGRES_USER
target_version=18.6
target_major=${target_version%%.*}
new_volume=dev-infra-postgres${target_major}-data
staging=dev-infra-postgres-migration
bootstrap=dev_infra_system_${target_major}_$(cat /proc/sys/kernel/random/uuid | cut -c1-8)
export POSTGRES_PASSWORD
POSTGRES_PASSWORD=$(PYTHONPATH=/opt/dev-infra/src "$(cat /opt/dev-infra/.python)" -c 'from pathlib import Path; from dev_infra.instance import Instance; print(Instance(Path("/opt/dev-infra")).values["POSTGRES_PASSWORD"])')
if docker volume inspect "$new_volume" >/dev/null 2>&1; then
  echo "目标卷已存在，请选择一个全新的卷。" >&2
  exit 1
fi
docker pull "postgres:$target_version"
docker volume create --label io.dev-infra.managed=true \
  --label io.dev-infra.instance=/opt/dev-infra \
  --label io.dev-infra.service=postgres --label "io.dev-infra.scope=$target_major" "$new_volume"
docker run -d --name "$staging" --network none --memory 384m \
  -e "POSTGRES_USER=$bootstrap" -e "POSTGRES_DB=$bootstrap" -e POSTGRES_PASSWORD \
  --mount "type=volume,source=$new_volume,target=/var/lib/postgresql" "postgres:$target_version"
for attempt in {1..60}; do
  if docker exec "$staging" pg_isready -U "$bootstrap" -d "$bootstrap"; then break; fi
  sleep 1
done
docker exec "$staging" pg_isready -U "$bootstrap" -d "$bootstrap"
```

暂停源库写入并直传；失败时恢复旧服务的可写设置，保留新卷供检查：

```bash
source_sql() {
  docker exec -e PGOPTIONS='-c default_transaction_read_only=off' "$old" \
    psql -U "$old_user" -d postgres -v ON_ERROR_STOP=1 "$@"
}
unfreeze_source() {
  source_sql -c 'ALTER SYSTEM RESET default_transaction_read_only;' \
    -c 'SELECT pg_reload_conf();' >/dev/null || true
}
trap unfreeze_source ERR INT TERM
source_sql -c "ALTER SYSTEM SET default_transaction_read_only = 'on';" \
  -c 'SELECT pg_reload_conf();' \
  -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE backend_type = 'client backend' AND pid <> pg_backend_pid();"
docker exec "$old" pg_dumpall -U "$old_user" --clean --if-exists | \
  docker exec -i "$staging" psql -U "$bootstrap" -d "$bootstrap" -X -v ON_ERROR_STOP=1 --quiet
```

验收全部业务数据库、表行数、扩展、权限和关键业务查询。表行数可逐库比较：

```bash
table_counts() {
  docker exec -i "$1" psql -U "$2" -d "$3" -At -v ON_ERROR_STOP=1 <<'SQL'
SELECT format('SELECT %L, count(*) FROM %I.%I;', schemaname || '.' || tablename, schemaname, tablename)
FROM pg_tables WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
ORDER BY schemaname, tablename
\gexec
SQL
}
old_databases=$(docker exec "$old" psql -U "$old_user" -d postgres -At -c "SELECT datname FROM pg_database WHERE NOT datistemplate ORDER BY datname;")
new_databases=$(docker exec "$staging" psql -U "$bootstrap" -d postgres -At -c "SELECT datname FROM pg_database WHERE NOT datistemplate AND datname <> '$bootstrap' ORDER BY datname;")
[[ "$old_databases" == "$new_databases" ]]
while IFS= read -r database; do
  old_counts=$(table_counts "$old" "$old_user" "$database")
  new_counts=$(table_counts "$staging" "$bootstrap" "$database")
  [[ "$old_counts" == "$new_counts" ]]
done <<<"$old_databases"
```

初始化角色持有系统对象，不能强行 REASSIGN/DROP。将它保留为禁止登录、没有密码的系统角色，
业务账号、密码与业务对象所有权由 dump 恢复。验收成功后整理统计信息、停掉临时实例和旧实例：

```bash
docker exec "$staging" vacuumdb -U "$bootstrap" --all --analyze-only
docker exec "$staging" psql -U "$bootstrap" -d postgres -v ON_ERROR_STOP=1 \
  -c "DROP DATABASE \"$bootstrap\";" \
  -c "ALTER ROLE \"$bootstrap\" NOLOGIN PASSWORD NULL;"
source_sql -c 'ALTER SYSTEM RESET default_transaction_read_only;'
# 此处不 reload：旧服务内存中保持只读直到停止。
docker stop "$old"
docker stop "$staging"
docker rm "$staging"
trap - ERR INT TERM
unset POSTGRES_PASSWORD
```

最后执行 `dev-infra remove postgres`，在 `config edit --instance` 中设置
`POSTGRES_DATA_VOLUME` 为新卷，在 `config edit --versions` 中设置目标 `POSTGRES_VERSION`，
然后 `dev-infra start postgres`。检查 `list`、连接和业务查询后，再恢复应用。
切换前任一步失败都不删除旧卷；切换失败时保留两个卷，用旧版本与旧卷重新启动旧服务。
清理旧卷前先运行 `data list` 查看数据卷和容器引用，确认后再执行 `data prune --yes`。

## 其他中间件跨范围

- **MySQL**：先按[官方升级路径](https://dev.mysql.com/doc/refman/8.4/en/upgrade-paths.html)运行
  目标版本的升级检查。当前配置启用了 `mysql_native_password`，进入不支持它的版本前先迁移
  账号认证、升级客户端，并修改 `config/mysql/my.cnf` 和初始化脚本。保留数据时在新卷完成
  逻辑导入及验证，随后修改实例卷名和版本覆盖、删除旧容器、启动新实例。
- **Redis**：确认[持久化格式和模块](https://redis.io/docs/latest/operate/oss_and_stack/install/upgrade/cluster/)
  支持目标版本。停止写入、完成持久化，在新卷验证恢复与应用读取；只用作可丢弃缓存时可按下一节重置。
- **Kafka**：本实例是单节点 KRaft。按[目标版本升级说明](https://kafka.apache.org/43/getting-started/upgrade/)
  处理支持的源版本、metadata.version 和 feature level，验证主题、消费组、消费者及生产者。
  使用新卷时保持 Cluster ID 与元数据一致；metadata 提升后的回退遵循该版本的官方约束。
- **RustFS**：按[官方部署说明](https://docs.rustfs.com/en/installation/container/docker)和目标发布记录
  确认格式兼容；跨格式使用独立目标实例，通过 S3 API 迁移对象，核对对象数量、内容、元数据和桶策略。
  一并验证 `rustfs/rc`，之后切换实例卷名、版本与入口。
- **Mailpit**：参考[官方镜像说明](https://mailpit.axllent.org/docs/install/docker/)与目标发布记录，
  在新卷测试现有 SQLite 邮件库。验证邮件数量、SMTP 与 UI 后切换；开发邮件可丢弃时直接重置。

这些迁移路径需要针对目标版本与数据验收，没有通用“强制跨主版本”命令。

## 数据可丢弃时

先用 `config edit --versions` 声明已确认的目标版本。需要换卷名时用 `config edit --instance`
设置新卷。先查看数据卷，再显式重置或清理：

```text
dev-infra data list
dev-infra data reset redis --yes
dev-infra data prune --yes
```

重置只删除所选服务当前声明的卷，先校验配置和目标镜像，再停止、删除容器、重建卷并启动。
`data prune` 只删除具有匹配本实例与服务管理标签、且不属于当前声明也没有容器引用的闲置卷。旧卷名和历史归属记录仅用于识别，不构成删除授权；`data list` 显示归属，预先存在的外部卷会保留。删除前重新检查标签、当前声明和容器引用，不执行全局 volume prune。
