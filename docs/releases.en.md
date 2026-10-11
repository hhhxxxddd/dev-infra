# Release packages and controller updates

[简体中文](releases.md) · [Configuration and installation](config.en.md)

## Complete release packages

The dev-infra release assets are built independently of the dev-tools repository and modules.
The ZIP contains the controller, Windows/WSL entrypoints, installation/removal scripts, Compose,
version defaults, instance template, config/init, bilingual documentation and MIT license.
Native `.python`, `.source`, `.env`, `versions.local.env`, state, backups, private hosts and caches are excluded.

Build a candidate with native Python 3.14; uncommitted changes are allowed:

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m dev_infra.release --output dist
python -m dev_infra.package_smoke dist/dev-infra-0.3.0.zip
```

Outputs are `dev-infra-<version>.zip`, `SHA256SUMS` and `dev-infra.json` for Scoop installation.
Filenames use the shared version declaration. Fixed ordering, timestamps, LF line endings and
uncompressed entries make Windows and Linux builds byte-identical. `.release.json` uses schema_version=1
and records the repository, version, Git commit, dirty flag and per-file SHA256 values. Dirty candidates cannot be official releases.

Official builds require a clean checkout with the official origin, HEAD matching the version tag,
and version-specific release notes:

```powershell
python -m dev_infra.release --tag v0.3.0 --official --output dist
```

This command does not create a tag, publish a Release or push a bucket. Notes live in
[docs/releases/v0.3.0.md](releases/v0.3.0.md); publishing rewrites local documentation links to the
corresponding GitHub commit. The Scoop manifest is generated as an official Release asset and
synchronized by [hxd-box](https://github.com/hhhxxxddd/hxd-box). This repository's release workflow
does not automatically push bucket updates.

## Verification and installation

Download the ZIP and `SHA256SUMS` only from the
[official GitHub Releases](https://github.com/hhhxxxddd/dev-infra/releases), verify the ZIP's SHA256,
then extract it. Offline `package_smoke` checks the ZIP and per-file inventory, binds a temporary
external Python, and invokes the actual native entrypoint for version, help and configuration queries.
It does not access Docker or install globally. Isolated installer tests separately verify repeated
deployment and preservation of local data.

After extraction:

```powershell
.\scripts\install.ps1
```

Deploy WSL only:

```bash
sudo DEV_INFRA_PYTHON=/path/to/python3.14 bash scripts/install.sh
```

Both platforms require existing native Python 3.14; WSL still needs rsync, flock and Docker CLI.
Package installation does not require a Git checkout. Deployment reuses existing interpreter bindings,
retains instance settings, image overrides, state and backups, and does not restart middleware.

SHA256 values and the receipt prove content integrity, not a publisher signature. Repository and
commit fields in a receipt do not establish identity. Users must obtain local packages from the official
channel and compare checksums from that same channel. Automatic downloads use only the official
repository's stable Release API, ZIP and checksum file, rejecting mismatched versions, hashes and unsafe paths.

## Two controller update channels

```text
dev-infra self status
dev-infra self upgrade
dev-infra self update
```

`self status` reports the current channel. Git installations record `.source`; `self upgrade`
verifies the official origin, requires a clean branch tracking origin, fetches source and only
fast-forwards. It never overwrites local changes or divergent histories automatically. Package
installations retain `.release.json` without recording a temporary extraction directory;
`self upgrade` downloads and verifies the latest stable Release before deployment. Windows deploys
both platforms; native WSL deploys only the backend. Scoop installations update through Scoop.

`self update` only redeploys current code; it never fetches source or downloads a new version.
`--source <directory>` selects an official Git checkout or a verified extracted package; an explicit
package is deployed directly. No channel upgrades Python or middleware. Native preferences and instance data remain separate.
