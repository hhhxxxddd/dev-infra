# dev-infra

Own shared local middleware, not application project scanning or language runtime installation.
Compose is the sole Docker runtime adapter. Windows and WSL share one WSL instance and Docker backend.
Use Python 3.14 on both platforms. Keep backend interpreter identity in native `.python` bindings
and any private controller runtime in ignored `host/`; preserve both during deployment.

- Keep service metadata and compatible scopes in the catalog; CLI help and parsing use one catalog.
- Keep preferences user-native, instance accounts/ports in `.env`, and local image upgrades in
  `versions.local.env`. Never source configuration as executable shell code.
- Resolve language before help; default zh, en through preferences. Keep messages in the central
  catalog, preserve raw third-party output and stable JSON/status identifiers.
- Queries and dry-run never create config, volumes, images or containers. Validate all arguments
  before Docker access or mutations.
- Share an upgrade plan between query/preview/execution. Pin resolved digests, pull before cutover,
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
uvx ruff check src scripts/dev-infra.py tests
uvx ruff format --check src scripts/dev-infra.py tests
```
