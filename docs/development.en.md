# Development and verification

[中文](development.md) · [README](../README.en.md)

## Structure

```text
src/dev_infra/
  cli.py             Command catalog, parsing, preflight, Windows transport
  catalog.py         Service metadata, groups, compatible scopes
  settings.py        User preferences, editors, sudo identity
  instance.py        Data parsing, atomic writes, operation lock
  registry.py        Docker Hub, stable releases, pagination
  planning.py        Shared query/execution upgrade plan
  docker.py          Docker/Compose argv and volume compatibility
  operations.py      Lifecycle, upgrade execution, reset, deployment
  data.py            Streaming backup, ownership, scoped cleanup
  presentation.py    Chinese/English catalog and presentation
scripts/             Native entrypoints, installation and removal
tests/               Isolated controller, backup, registry and adapter checks
tests/integration/   Real lifecycle checks in an independent Docker project
```

Python 3.14 standard library only; other minor versions are unsupported.
Compose is the sole container execution backend.
Windows owns local preferences and forwards operations; runtime, instance files and operation
locks remain in the shared WSL backend.

## Checks

Windows:

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m unittest discover -v tests
uvx ruff check src scripts/dev-infra.py tests
uvx ruff format --check src scripts/dev-infra.py tests
```

WSL:

If using the private deployed interpreter, add its directory to this shell's PATH first:

```bash
export PATH="$(dirname "$(cat /opt/dev-infra/.python)"):$PATH"
```

```bash
export PYTHONPATH="$PWD/src"
python3.14 -m unittest discover -v tests
uvx ruff check src scripts/dev-infra.py tests
uvx ruff format --check src scripts/dev-infra.py tests
bash -n dev-infra
for file in scripts/*.sh; do bash -n "$file"; done
shellcheck dev-infra scripts/*.sh
```

Parse each `scripts/*.ps1` with the PowerShell parser before bootstrap testing. CI covers Linux
and Windows, Python 3.14, with the same unit, format and entrypoint syntax checks. Unit tests
never connect to real databases or Docker Hub. Backups exercise real streaming compression and
failure cleanup, using an isolated local process instead of an external dump.

## Real lifecycle

```bash
python3.14 tests/integration/lifecycle.py
```

Requires Docker and the already-installed declared Redis image. Uses a random Compose project
and temporary volume, no host ports and no image downloads. Checks startup, health, retained data
after recreate, retained volumes after container removal, reset and cleanup. After deployment,
verify Windows `-NoProfile`, WSL entrypoints, language, JSON, read-only upgrade plans and existing
service health.

## Documentation

Keep both READMEs and configuration/upgrade guides aligned in commands, defaults and examples.
Validate local Markdown links, TOML examples and Bash migration example syntax. Installation
delivers complete documentation; default templates retain Chinese guidance.
