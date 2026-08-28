# Publishing

The release pipeline is deliberately explicit:

1. Develop and test the module in its own repository.
2. Build the host-defined `.ocp` v1 bundle in module CI.
3. Run the pinned host verifier locally as a pre-PR check.
4. Calculate SHA-256 over the complete `.ocp` file.
5. Publish the immutable, versioned `.ocp` release, preferably as a GitHub Release in the module repository.
6. Add or update `registry/modules/<module-id>.json` in a registry pull request.
7. Run local registry validation and the deterministic build.
8. Registry PR CI downloads every new release, checks its digest, and runs the pinned host verifier.
9. Obtain registry review and merge only after all CI gates pass.
10. Build and atomically deploy `dist/` as one release.

For example:

```bash
sha256sum energy-analysis-1.4.0.ocp
uv run python scripts/validate_registry.py --base-ref origin/main
uv run python scripts/build_registry.py --output dist
git diff --exit-code -- dist
```

The metadata validator checks Registry v1 structure and publishing policy. The separate artifact gate compares the current registry with the PR base, so only previously unpublished `module ID + version` identities are downloaded. Published releases are skipped by this gate and remain protected by the independent immutability check. All channels use the same artifact-verification contract.

## `.ocp` v1 verification contract

Before proposing a release, contributors should verify the local artifact using the Open City Planner host contract:

```bash
uv run python -m app.cli.modules verify /path/to/energy-analysis-1.4.0.ocp
```

The single source of truth for `OCP_HOST_VERIFIER_REF` and its repository is [`.github/ocp-host-verifier.json`](../.github/ocp-host-verifier.json). The current reviewed pin is `b8c4db7f3246d21c53a1b5633915be16bb84a633`; workflows, scripts, and tests read the config rather than carrying independent pins. CI checks out that exact commit under `_host-verifier/`, installs `backend/uv.lock` with `uv sync --frozen --extra dev --no-editable` and the frontend lockfile with `pnpm install --frozen-lockfile`, then invokes:

```text
_host-verifier/backend/.venv/bin/python -m app.cli.modules --root <temporary-state> verify <temporary-artifact.ocp>
```

The subprocess uses an argv list with `shell=False` and a 10-minute timeout. After the host returns JSON, CI compares `module_id` and `version` with Registry metadata. `verify` must not create `modules.lock`; no install, enable, or disable command is executed.

## Network and digest gate

Before opening a connection, the downloader reuses `scripts.registry.validate_artifact_url`. Initial URLs remain limited to the versioned module path on `packages.stadtplaner.oklabflensburg.de` or a version-bound GitHub Release. This exact-host allowlist prevents PR metadata from selecting localhost, private/link-local addresses, metadata services, or arbitrary community hosts.

Downloads use a 30-second connect/read socket timeout, a 10-minute total deadline, a 512 MiB maximum matching `.ocp` v1, one-MiB streaming chunks, and at most three redirects. `Content-Length` is rejected early when oversized, but the streaming counter is authoritative. Temporary files use unpredictable per-release directories and are removed after success or failure.

Static registry-host URLs may not redirect. GitHub Releases may redirect only from `github.com` to the observed `release-assets.githubusercontent.com` service over HTTPS. Every hop is checked; signed query parameters created by GitHub are accepted only on that runtime redirect and are never stored or logged from Registry metadata. Other targets and redirect loops fail closed.

SHA-256 is accumulated while streaming the complete `.ocp` bytes. CI compares it with Registry metadata before any host code sees the file. A mismatch, non-2xx response, timeout, oversized response, forbidden redirect, malformed verifier output, bundle identity mismatch, or verifier failure blocks the PR.

Updating the verifier pin requires a normal reviewed pull request justified by an official `.ocp` contract revision, reviewed host release, or security fix. Update only `.github/ocp-host-verifier.json`; CI validates the full lowercase commit SHA and fails if checkout or HEAD does not match. There is no automatic latest-host lookup.

Reviewed-community modules follow the same technical pipeline. The additional work is human verification of publisher, public/reviewable source repository, license, maintainer provenance, immutable artifact location, and review evidence; there is no separate community registry or private-artifact credential flow.

After discovery, a future admin-side consumer may download a selected `id@version`, verify SHA-256, run `.ocp` verification, and invoke the existing installer. This repository does not implement that consumer, runtime downloads, automatic installation, or transitive dependency selection.
