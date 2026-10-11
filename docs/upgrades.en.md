# Middleware upgrades and migrations

[中文](upgrades.md) · [README](../README.en.md)

## Routine upgrades

```text
dev-infra check --updates
dev-infra upgrade
dev-infra upgrade redis
dev-infra check --updates postgres --to 18.6
dev-infra upgrade postgres --to 18.6
dev-infra check --updates --no-backup
dev-infra upgrade --no-backup
```

`check --updates` shows versions, compatible scopes, backup policy and execution steps read-only,
without pulling images or modifying the instance. It shares the plan with `upgrade`. Failed
queries preserve other results; execution requires every query to succeed and no migration blocks.
On check, `--to`, `--backup` and `--no-backup` require `--updates`; `--json` controls output format only.
RC, preview and edge releases are excluded.

| Service | Automatic scope | Changes outside the scope |
| --- | --- | --- |
| MySQL | Current LTS branch, e.g. 8.4 | Upgrade checks, account compatibility, supported migration to a new volume |
| PostgreSQL | Current major, e.g. 18 | Logical migration or pg_upgrade; validate and switch volumes |
| Redis | Current major, e.g. 8 | Validate RDB/AOF and modules in a new volume; disposable caches can be reset |
| Kafka | Current minor, e.g. 4.3 | Follow target KRaft/metadata.version requirements before changing declarations |
| RustFS | Current major, e.g. 1 | Check storage format and release notes; migrate through S3 if incompatible |
| Mailpit | Current major, e.g. v1 | Validate SQLite compatibility in a new volume or reset mail |
| RustFS client | Current minor, e.g. v0.1 | Updated with RustFS; validate commands and authentication before changing minor |

`--to` selects a stable version or branch for one service. The controller resolves its digest and
retains compatibility checks. There is no force flag bypassing migration. Known downgrades are
rejected; use the latest stable release when a floating tag cannot prove upgrade direction.
Local `versions.local.env` saves concrete versions and digests, including upgrades from fixed tags.

Affected MySQL/PostgreSQL databases are backed up by default. A stopped database blocks the upgrade
until started or explicitly skipped with `--no-backup`. `operation.backup = false` changes the
default. `data backup` always requests a backup explicitly.

## Recovery

All target images are pulled before version declarations or containers change. Pull failures retain existing declarations and containers.
`dev-infra check` / `check --json` read the previous upgrade stage, error, completed steps, per-service state and backup paths, with diagnostic, log and retry commands. The journal lives at `/opt/dev-infra/.state/last-upgrade.json`; each completed backup is recorded immediately.

Fix the environment, configuration or startup failure, then rerun the same `upgrade` command. A retry validates current state and a new plan instead of blindly resuming the old journal. Success clears the old failure. Databases never automatically switch back to old images; reverting an image does not revert an upgraded data format.


## PostgreSQL major versions

Minor releases within a major can reuse data. Major changes require a logical migration or
pg_upgrade; see the [official guide](https://www.postgresql.org/docs/18/upgrading.html). PostgreSQL
18 and newer use a volume mounted at `/var/lib/postgresql`, with the image's default `<major>/docker`
data directory.

The following direct logical transfer creates no dump backup file. The example is 17→18. For
another major, select a released target supporting every required extension. Stop database clients
and application projects until cutover validation is complete. Run the following blocks in one WSL
Bash session with Docker permission and read access to `/opt/dev-infra/.env`.

Prepare the target; the default source container is `dev-postgres-1`:

```bash
set -Eeuo pipefail
old=dev-postgres-1
old_user=dev  # Replace with the current POSTGRES_USER
target_version=18.6
target_major=${target_version%%.*}
new_volume=dev-infra-postgres${target_major}-data
staging=dev-infra-postgres-migration
bootstrap=dev_infra_system_${target_major}_$(cat /proc/sys/kernel/random/uuid | cut -c1-8)
export POSTGRES_PASSWORD
POSTGRES_PASSWORD=$(PYTHONPATH=/opt/dev-infra/src "$(cat /opt/dev-infra/.python)" -c 'from pathlib import Path; from dev_infra.instance import Instance; print(Instance(Path("/opt/dev-infra")).values["POSTGRES_PASSWORD"])')
if docker volume inspect "$new_volume" >/dev/null 2>&1; then
  echo "Target volume already exists; choose a fresh volume." >&2
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

Freeze source writes and stream the migration. Failure restores source writability and retains the
new volume for investigation:

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

Validate every business database, table counts, extensions, permissions and representative queries.
Compare table counts for each database:

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

The bootstrap role owns required system objects. Retain it with login disabled and its password
removed; do not force REASSIGN/DROP. The dump restores application accounts, passwords and business
object ownership. After validation, analyze the target and stop both staging and source:

```bash
docker exec "$staging" vacuumdb -U "$bootstrap" --all --analyze-only
docker exec "$staging" psql -U "$bootstrap" -d postgres -v ON_ERROR_STOP=1 \
  -c "DROP DATABASE \"$bootstrap\";" \
  -c "ALTER ROLE \"$bootstrap\" NOLOGIN PASSWORD NULL;"
source_sql -c 'ALTER SYSTEM RESET default_transaction_read_only;'
# Do not reload here: the source remains read-only in memory until stopped.
docker stop "$old"
docker stop "$staging"
docker rm "$staging"
trap - ERR INT TERM
unset POSTGRES_PASSWORD
```

Run `dev-infra remove postgres`. Set `POSTGRES_DATA_VOLUME` to the new volume through
`config edit --instance`, and the target `POSTGRES_VERSION` through `config edit --versions`.
Run `dev-infra start postgres`, validate status, connections and business queries, then resume
applications. Failures before cutover never delete the old volume. If cutover fails, retain both
volumes and start the old service using its original version and volume. Inspect obsolete volumes
and container references with `data list`, then explicitly use `data prune --yes`.

## Other middleware scope changes

- **MySQL**: follow the [supported upgrade paths](https://dev.mysql.com/doc/refman/8.4/en/upgrade-paths.html)
  and run the target upgrade checker. Current configuration enables `mysql_native_password`; before
  a target removes it, migrate authentication, update clients, and adjust `config/mysql/my.cnf` and
  initialization scripts. Import and validate retained data in a new volume before changing volume
  and version declarations, removing the old container and starting the target.
- **Redis**: verify target support for [persistence and modules](https://redis.io/docs/latest/operate/oss_and_stack/install/upgrade/cluster/).
  Stop writes, finish persistence, validate restore and application reads in a new volume. Disposable
  caches can follow the reset procedure below.
- **Kafka**: this instance uses single-node KRaft. Follow the [target upgrade guide](https://kafka.apache.org/43/getting-started/upgrade/)
  for supported source versions, metadata.version and feature levels. Validate topics, groups,
  consumers and producers. A new volume must retain consistent Cluster ID and metadata; follow the
  target's documented rollback constraints after metadata upgrades.
- **RustFS**: review [deployment documentation](https://docs.rustfs.com/en/installation/container/docker)
  and target release notes for format compatibility. For incompatible storage formats, transfer to
  a separate target through S3, validating object counts, content, metadata and bucket policy.
  Validate `rustfs/rc` too before switching volumes, versions and endpoints.
- **Mailpit**: review [image documentation](https://mailpit.axllent.org/docs/install/docker/) and target
  release notes; test the SQLite mail database in a new volume. Validate mail count, SMTP and UI
  before switching. Reset disposable development mail instead if appropriate.

These paths need target-specific validation; there is no generic force-major-upgrade command.

## Disposable data

Declare the confirmed target using `config edit --versions`. If using a new volume name, set it
through `config edit --instance`. Inspect the volumes, then explicitly reset or clean up:

```text
dev-infra data list
dev-infra data reset redis --yes
dev-infra data prune --yes
```

Reset deletes only the selected service's declared volume. It validates configuration and the
target image before stopping/removing containers and recreating the volume.
`data prune` deletes only idle volumes carrying matching instance and service management labels, excluding currently declared volumes and any container references. Old volume names and historical ownership records help identify volumes; they do not authorize deletion. `data list` shows ownership, and pre-existing external volumes are retained. Labels, current declarations and container references are checked again before deletion; no global volume prune runs.
