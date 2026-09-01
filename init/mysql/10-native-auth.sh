#!/usr/bin/env bash
set -Eeuo pipefail

# The official entrypoint creates MYSQL_USER first. Keep this compatibility
# account usable by older JDBC clients while root retains MySQL 8.4 defaults.
mysql --protocol=socket -uroot -p"${MYSQL_ROOT_PASSWORD}" <<SQL
ALTER USER '${MYSQL_USER}'@'%' IDENTIFIED WITH mysql_native_password BY '${MYSQL_PASSWORD}';
GRANT ALL PRIVILEGES ON \`${MYSQL_DATABASE}\`.* TO '${MYSQL_USER}'@'%';
FLUSH PRIVILEGES;
SQL
