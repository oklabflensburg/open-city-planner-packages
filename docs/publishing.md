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
10. Build and atomically deploy `dist/` as one Registry release.
11. Explicitly mirror the already reviewed bytes outside the Registry release tree.
12. In a second reviewed pull request, promote `artifact.url` to the canonical mirror URL.

For example:

```bash
sha256sum energy-analysis-1.4.0.ocp
uv run python scripts/validate_registry.py --base-ref origin/main
uv run python scripts/build_registry.py --output dist
git diff --exit-code -- dist
```

The metadata validator checks Registry v1 structure and publishing policy. The separate artifact gate compares the current registry with the PR base, so only previously unpublished `module ID + version` identities are downloaded. Published releases are skipped by this gate and remain protected by the independent immutability check. All channels use the same artifact-verification contract.

After a module's first merge, its publisher ID, classification, source repository, and Registry v1 module-level license are protected provenance. Display name, module name/description, homepage, documentation URL, and publisher display name remain editable in reviewed pull requests. A real publisher change, repository transfer, reclassification, or license-family change requires an explicit Registry governance/schema follow-up; do not rewrite the existing module metadata silently.

## `.ocp` v1 verification contract

Before proposing a release, contributors should verify the local artifact using the Open City Planner host contract:

```bash
uv run python -m app.cli.modules verify /path/to/energy-analysis-1.4.0.ocp
```

The single source of truth for `OCP_HOST_VERIFIER_REF` and its repository is [`.github/ocp-host-verifier.json`](../.github/ocp-host-verifier.json). The current reviewed pin is `81844b666aca8356f9c5cb9a86f00cf15b784f79`; workflows, scripts, and tests read the config rather than carrying independent pins. CI checks out that exact commit under `_host-verifier/`, installs `backend/uv.lock` with `uv sync --frozen --extra dev --no-editable` and the frontend lockfile with `pnpm install --frozen-lockfile`, then invokes:

```text
_host-verifier/backend/.venv/bin/python -m app.cli.modules --root <temporary-state> verify <temporary-artifact.ocp>
```

The verifier subprocess sets `OCP_EXCLUDED_BUILTIN_MODULES` to the candidate module ID so a reviewed built-in-to-external cutover is checked through the host's explicit external-ownership path. This does not install or enable the candidate.

The subprocess uses an argv list with `shell=False` and a 10-minute timeout. After the host returns JSON, CI compares `module_id` and `version` with Registry metadata. `verify` must not create `modules.lock`; no install, enable, or disable command is executed.

## Network and digest gate

Before opening a connection, the downloader reuses `scripts.registry.validate_artifact_url`. Initial URLs remain limited to the versioned module path on `packages.stadtplaner.oklabflensburg.de` or a version-bound GitHub Release. This exact-host allowlist prevents PR metadata from selecting localhost, private/link-local addresses, metadata services, or arbitrary community hosts.

Downloads use a 30-second connect/read socket timeout, a 10-minute total deadline, a 512 MiB maximum matching `.ocp` v1, one-MiB streaming chunks, and at most three redirects. `Content-Length` is rejected early when oversized, but the streaming counter is authoritative. Temporary files use unpredictable per-release directories and are removed after success or failure.

Static registry-host URLs may not redirect. GitHub Releases may redirect only from `github.com` to the observed `release-assets.githubusercontent.com` service over HTTPS. Every hop is checked; signed query parameters created by GitHub are accepted only on that runtime redirect and are never stored or logged from Registry metadata. Other targets and redirect loops fail closed.

SHA-256 is accumulated while streaming the complete `.ocp` bytes. CI compares it with Registry metadata before any host code sees the file. A mismatch, non-2xx response, timeout, oversized response, forbidden redirect, malformed verifier output, bundle identity mismatch, or verifier failure blocks the PR.

Updating the verifier pin requires a normal reviewed pull request justified by an official `.ocp` contract revision, reviewed host release, or security fix. Update only `.github/ocp-host-verifier.json`; CI validates the full lowercase commit SHA and fails if checkout or HEAD does not match. There is no automatic latest-host lookup.

Reviewed-community modules follow the same technical pipeline. The additional work is human verification of publisher, public/reviewable source repository, license, maintainer provenance, immutable artifact location, and review evidence; there is no separate community registry or private-artifact credential flow.

After discovery, a future admin-side consumer may download a selected `id@version`, verify SHA-256, run `.ocp` verification, and invoke the existing installer. This repository does not implement that consumer, runtime downloads, automatic installation, or transitive dependency selection.

## Immutable artifact mirror and bootstrap flow

Registry v1 uses bootstrap Option A. It needs no staging namespace or additional schema field:

1. **Phase 1:** publish the immutable GitHub Release URL and digest in a Registry pull request. CI downloads that exact URL, verifies SHA-256, and runs the pinned Host verifier.
2. **Phase 2:** after merge, the exact-SHA Production deployment automatically publishes every missing reviewed release into the persistent Registry mirror.
3. **Phase 3:** verify the public mirror URL and digest, then open a second reviewed Registry pull request that changes only `artifact.url` to the canonical Registry URL.

The one-time URL promotion is narrowly validated: GitHub Release to `/modules/<id>/<version>/<id>-<version>.ocp`, with the digest and every other release field unchanged. Once promoted, the mirror URL is immutable. GitHub repository, source commit, and source tag remain the provenance record.

The production publisher intentionally reuses the merged Registry metadata and the same bounded downloader, redirect policy, and SHA-256 implementation as the pull-request artifact gate. The exact URL and digest were already accepted by the pinned Host verifier before merge; production therefore does not install a second Host runtime merely to repeat parsing. Operators who have the pinned verifier checkout prepared may additionally pass `--host-verifier-root` to `scripts/publish_artifacts.py`; this still invokes only `verify`.

The normal flow for `analysis-areas@1.0.0` is:

```bash
# 1. Merge the Registry PR containing the GitHub Release URL.
# 2. That push starts the main workflow, which deploys the exact commit,
#    mirrors missing artifacts, and verifies their public bytes and headers.
# 3. Open a second reviewed PR changing only artifact.url to the mirror URL.
```

The publisher derives every target path from validated module ID and SemVer in
the exact deployed release. It checks existing files before opening a network
connection, downloads missing artifacts into randomized hidden `.partial` files,
checks the Registry digest, optionally calls the shared Host verifier, flushes
the complete file, and publishes with an atomic no-clobber link. Matching files
are idempotent successes; different content fails without overwrite. If one item
in a batch fails, earlier successful append-only publications remain and are
reported as `already-present` on retry.

After activation, newly published artifacts are streamed from their canonical
public URLs to verify SHA-256. Their responses must use
`application/octet-stream`, immutable caching, and `nosniff`. A canonical mirror
URL whose local file already exists is accepted without a download. If canonical
mirror metadata points to a missing local file, publication fails closed instead
of downloading recursively from the same Registry.

`playbooks/publish-artifact.yml` remains available for targeted recovery,
operations, debugging, and idempotent republish checks. It is not part of normal
publication. Disaster recovery for missing artifacts after URL promotion must
restore the original verified GitHub Release bytes through a separately reviewed
recovery procedure; the self-mirror URL is never treated as a bootstrap source.

Manual artifact publication is a recovery tool. Normal reviewed Registry
deployments publish missing immutable artifacts automatically.
