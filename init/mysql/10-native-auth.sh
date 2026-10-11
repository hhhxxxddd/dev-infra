#!/usr/bin/env bash
set -Eeuo pipefail

# The official entrypoint creates MYSQL_USER first. Keep this compatibility
# account usable by older JDBC clients while root retains MySQL 8.4 defaults.
sql_literal() {
  local value=$1
  value=${value//\'/\'\'}
  printf "'%s'" "$value"
}
sql_identifier() {
  local value=$1
  value=${value//\`/\`\`}
  # SQL identifier delimiters are literal backticks.
  # shellcheck disable=SC2016
  printf '`%s`' "$value"
}
account=$(sql_literal "${MYSQL_USER}")
password=$(sql_literal "${MYSQL_PASSWORD}")
database=$(sql_identifier "${MYSQL_DATABASE}")

# Use standard doubled quotes with a fixed connection-local SQL mode. Binary mode
# disables batch client commands, and MYSQL_PWD keeps the root password out of argv.
# Server syntax errors can echo SQL containing the password, so expose a safe failure.
if ! MYSQL_PWD="${MYSQL_ROOT_PASSWORD}" mysql --protocol=socket --user=root \
  --default-character-set=utf8mb4 --binary-mode \
  --init-command="SET SESSION sql_mode = 'NO_BACKSLASH_ESCAPES'" \
  >/dev/null 2>/dev/null <<SQL
ALTER USER ${account}@'%' IDENTIFIED WITH mysql_native_password BY ${password};
GRANT ALL PRIVILEGES ON ${database}.* TO ${account}@'%';
FLUSH PRIVILEGES;
SQL
then
  printf 'MySQL 开发账号初始化失败；请检查实例账号配置。\n' >&2
  exit 1
fi
