# CLI and data interface contract

[简体中文](cli-contract.md) · [Back to README](../README.en.md)

## Output and versions

`list`, `show`, `start`, `stop`, `restart`, `remove`, `check`, `upgrade`, `config`, `data` and `self`
support `--json`. Each invocation writes exactly one UTF-8 JSON object to stdout, including argument
errors, invalid configuration, execution failures and interruption. Controller diagnostics, editor
and installer output go to stderr. `logs` and `compose` retain their raw output; help and version
options produce text. Place `--json` before the argument separator `--`.

Known read-only `compose` passthrough commands do not initialize the instance. Mutations and unknown commands share the instance operation lock, including `config --output` and `wait --down-project`.

Every JSON result includes integer `schema_version = 1`, controlled by the public interface version
constant independently of the tool version and internal state format. Existing business fields stay
at the top level; there is no common `data` wrapper. Clients may ignore added fields. Removing,
renaming or changing the type of an existing field requires an interface version increase. Array
order is for presentation; correlate records by `service` / `volume` instead. Handle unknown state
values and do not parse localized text.

Failures include an `error` object with string `code`, string `message` and object `details`. Codes,
JSON keys and state identifiers do not change with language. `message` may be translated according
to preferences and must not drive program logic. `details` contains diagnostic data, optionally a
`detail` string; it is not executable code. Error diagnostics hide known credentials and SQL.
Successful `show` results mask passwords unless `--secrets` is explicit.

```json
{
  "schema_version": 1,
  "complete": false,
  "state": "error",
  "error": {
    "code": "unknown_service",
    "message": "Unknown service or group",
    "details": {"detail": "example"}
  }
}
```

Partial results and blocked upgrades retain business records and add a top-level `error`. `complete`
describes completion of this query or operation; it does not mean every service is healthy. A
successful `list` may include `exited` or `unhealthy` services, and `check --updates` may succeed while
finding updates. Also inspect service states, `blocked` and diagnostic checks.

## Exit codes

| Code | Contract |
| --- | --- |
| `0` | Query or operation succeeded; available updates and ordinary no-ops still succeed |
| `1` | Execution failure, incomplete query, partial backup, blocked upgrade or missing deletion confirmation |
| `2` | Argument syntax or semantics, including unknown services, invalid targets, target counts and option combinations |
| `130` | User interruption |

Invalid TOML / instance configuration and unknown internal state formats are environment or record
errors and return `1`. Windows forwarding preserves these codes. If the backend does not return a
supported single JSON object, the result is `transport_failed` with code `1`.

## Business results

| Command | Main fields and types |
| --- | --- |
| `list` / `show` / lifecycle | `complete: boolean`, `services: object[]`; records contain string `service/state/image/endpoint/volume`; show adds connection details |
| `check` | `complete: boolean`, `checks: object[]`, `recovery: object`; checks contain string `check/state` and optional `detail` |
| `check --updates` / `upgrade` | `complete/blocked/backup: boolean`, `services_selected: string[]`, `images: object[]`, `steps: string[]`; queries include `mode: "check"` |
| `data list` / `prune` | `complete: boolean`, `volumes: object[]`; prune may include `removed: string[]` |
| `data backup` | `complete: boolean`, `backups: object[]`; records contain `service/state`, with `path` on success |
| `data reset` | String `action/service/volume/state`, `users/steps: string[]` |
| `config` | String `path/state`, `exists: boolean`, `values: object` |
| `self status` | String `controller_version/python_version/python_executable/root/source/distro` |
| `self update` / `upgrade` | String `state`; optional string `channel/source` and provenance diagnostics |

Image records contain string `service/state/image/target`. Successfully resolved targets also have
string `version/version_key`, boolean `change` and nullable `reason`. An individual query failure
retains `state: "error"` and diagnostic string `error`; the top-level error code describes the overall
failure. `instance_signature` is internal validation data to detect configuration changes. Do not
edit it or submit the result as a directly executable upgrade plan.

Current core states follow; native Docker states retain their actual values.

| Object | States / identifiers |
| --- | --- |
| Service | `not_created/unavailable`, plus Docker `healthy/unhealthy/starting/running/created/exited/paused/restarting/removing/dead` |
| Image | `current/update_available/not_downloaded/blocked/error` |
| Check | `ok/error/skipped/warning` |
| Volume `state` | `active/referenced/obsolete/external` |
| Volume `ownership` | `managed/external` |
| Backup | `complete/skipped/error` |
| Recovery | `none/running/error/complete/unchanged/invalid` |
| Per-service upgrade progress | `pending/pulling/pulled/applying/complete/error` |

Volume records also contain string `service/volume/size/mountpoint` and `users: string[]`. `managed`
requires Docker labels matching this instance. Names, a historical ledger and the field itself do
not authorize deletion. Pruning rechecks labels, current configuration and all container references.
`reset --yes` explicitly destroys the selected active volume; `prune --yes` only removes idle old
volumes with proven ownership. Inspect them with `data list`. Queries do not create configuration,
volumes, images, containers, backups or repair records.

## Configuration fields

Configuration layers stay separate: native user `config.toml` holds preferences, the WSL instance
`.env` holds ports/accounts/volumes, and `versions.local.env` holds local image version overrides.
Windows does not forward its preferences file path to WSL.

| Preference | Type and default |
| --- | --- |
| `language` | `"zh"` (default) or `"en"` |
| `editor` | String argv array, default `[]`, using existing editor fallbacks |
| `wsl.distro` | Nonempty string, default `"Ubuntu"` |
| `operation.wait_timeout` | Integer `1–3600`, default `240` |
| `operation.backup` | Boolean, default `true` |

Unknown fields and incorrect types are rejected. Missing fields use defaults without query writes.
Instance ports must be unique and within `1–65535`; volume names must be legal and unique. Version
overrides accept only known version catalog keys and stable version formats. See
[configuration](config.en.md) for field details.

## Recovery records and backup boundaries

The `recovery` object in `check --json` always includes `state`, `needs_attention: boolean`,
`journal: string`, `automatic_rollback: false` and `recommendations: object[]`. Historical records may
also include failed `stage`, `active_service`, timestamps, `error`, `completed_steps: string[]`,
`backups: object[]` and `services: object[]`. Timestamps are timezone-aware ISO 8601 UTC strings;
unfinished times may be null. Historical diagnostic errors contain `type/code/message`.
Recommendation `action` values are stable identifiers and `argv` is an argument array. Queries only
display recommendations; they never execute them. Retries revalidate and never automatically roll
back databases.

`.state/last-upgrade.json` and `.state/volumes.json` use independent `format_version = 1`:

```json
{"format": "dev-infra.state", "format_version": 1, "payload": {}}
```

`payload` preserves the original upgrade record or volume-reference mapping. Existing unversioned
local records remain readable without migration or lost references. The next valid operation writes
the current format. Unknown versions and damaged records produce diagnostics while retaining the
original file. Upgrades do not replace unknown journals, and pruning does not use an invalid ledger
to remove volumes. Inspect the file before explicit repair. Atomic writes and the instance operation
lock continue to protect normal updates.

Backups are SQL gzip files. Successful records include a path; failed dumps do not publish partial
files. They are not raw database volume snapshots. This interface promises no automatic restoration,
migration or rollback. Before restoration, verify database versions, extensions/plugins, account
permissions and target configuration, then explicitly import and validate data using database tools.
Completed backups and failed stages remain in upgrade diagnostics. See
[upgrades](upgrades.en.md) for procedures and cross-version migration.
