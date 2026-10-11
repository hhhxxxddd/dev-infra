# dev-infra

Own shared local middleware, not application project scanning or language runtime installation.
Compose is the sole Docker runtime adapter. Windows and WSL share one WSL instance and Docker backend.
Use externally managed native Python 3.14 on both platforms. Resolve explicit DEV_INFRA_PYTHON,
then an existing native `.python` binding, then PATH; fail on invalid explicit paths or bindings.
Validate platform, version and required standard-library modules before deployment. Record the
real interpreter path in `.python`; deployment and uninstall never install, upgrade or remove
external Python. Shared base interpreters are allowed; application code, dependencies and
configuration remain separate. Preserve bindings and legacy private `host/` during deployment.

- Keep service metadata and compatible scopes in the catalog; CLI help and parsing use one catalog.
- Keep preferences user-native, instance accounts/ports in `.env`, and local image upgrades in
  `versions.local.env`. Never source configuration as executable shell code.
- Resolve language before help; default zh, en through preferences. Keep messages in the central
  catalog, preserve raw third-party output and stable JSON/status identifiers.
- Queries never create config, volumes, images, containers or backups. Action commands execute
  validated plans; do not expose `--dry-run` switches. Validate all arguments and require explicit
  data-deletion confirmation before Docker access or mutations.
- Share an upgrade plan between `check --updates` and execution, including target versions and
  backup preferences. Pin resolved digests, pull before cutover,
  record failures and completed steps, and never auto-downgrade database storage.
- Block incompatible existing volumes. Only explicit reset may discard selected active data;
  old-volume cleanup must prove ownership and exclude current or container-referenced volumes.
- Serialize mutations with the backend instance lock. Preserve local preferences, overrides,
  ownership records, backups and data during deployment.
- Verify Git origin before executing a checkout installer. Parse every PowerShell installer before
  bootstrap tests. Resolve source paths from entrypoints; never track machine identity or real secrets.
- Keep README/config/upgrade/development documents aligned in zh/en and deliver them in deployments.
- Run native Windows/WSL unittest, Ruff check/format, Bash syntax and ShellCheck checks. Integration
  tests must isolate Compose project names and volumes, use installed images, and clean up.

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m unittest discover -v tests
uvx ruff check src scripts tests
uvx ruff format --check src scripts tests
```
