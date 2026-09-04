# Central OCP Builder of Record

`ocp-builder v1` is the single build path for first-party `.ocp` candidates. GitHub module
repositories remain authoritative for reviewed source and immutable tags. This repository is
authoritative for the build procedure, candidate provenance, Registry review, and—after a
separate promotion step—artifact distribution.

## Existing infrastructure audit

Issue #35 extends the existing Registry pipeline; it does not introduce another Registry format
or generator.

| Existing component | Reused responsibility |
| --- | --- |
| `scripts/build_registry.py` | deterministic Registry v1 `registry/` → `dist/` generation |
| `scripts/verify_artifacts.py` | bounded downloads, SHA-256 checks, pinned Host checkout and bundle verification |
| `.github/ocp-host-verifier.json` | immutable Host verifier commit |
| `scripts/registry.py` | schema, hosting policy, canonical JSON and published-release immutability |
| `.github/workflows/registry.yml` | authoritative Registry PR and production deployment gates |

Before this change there was no allowlisted source intake, immutable tag resolution, generic
backend/frontend build, independent double build, candidate provenance, or central recovery
workflow. Those capabilities now live in `scripts/ocp_builder.py` and
`.github/workflows/ocp-builder.yml`.

## Source intake and build contract

The only user inputs are `module_id` and `source_tag`; the workflow also asks reviewers for a
planned channel. Repository, classification, publisher, and license come exclusively from
`config/first-party-modules.yaml`. Version is parsed from an exact `v<SemVer>` tag. Arbitrary
repository URLs, source commits, artifact URLs, and digests are not accepted as inputs.

The builder fetches the tag into a temporary Git repository, dereferences annotated or
lightweight tags with `^{commit}`, checks out that exact commit, and checks all of:

- `module.yaml.id` and tag version;
- backend project name/version against `module.yaml`;
- frontend package name, module ID, and both frontend versions against `module.yaml`;
- exactly one built wheel and its embedded name/version.

The v1 source layout is `module.yaml`, `backend/pyproject.toml`, and optionally
`frontend/package.json` plus `frontend/module.json`. Backend-only modules are supported.
Backends use `uv build --wheel`; frontends use a frozen pnpm install, available typecheck/test
scripts, `pnpm deploy`, and a central deterministic archive implementation. The central core has
no package-name or release-version special cases.

The existing Host bundle writer assembles Bundle Format v1 with the manifest, wheel, optional
frontend archive, source repository/tag/commit, license, and build workflow. This deliberately
does not redesign `.ocp`.

## Reproducibility and Host contract

Each request performs two complete builds in separate source checkouts and output trees. Both
start from the same tag-resolved commit and control `SOURCE_DATE_EPOCH`, ordering, timestamps,
ownership, modes, gzip metadata, and archive contents. A byte-level SHA-256 mismatch stops before
candidate creation.

The resulting candidate first passes the existing pinned, read-only Host bundle verifier. It then
passes a fresh-state generic lifecycle: verified dependency download by reviewed Registry digest,
install disabled, inventory, dependency enablement, candidate enablement/migration preflight,
backend/frontend discovery environment, disable, and re-enable. Any failed command or identity
mismatch is fatal. Module-specific public-contract fixtures may be added declaratively later;
they must not introduce module branches in the builder core.

## Candidate and review lifecycle

Successful output contains:

```text
<module>-<version>.ocp
<module>-<version>.ocp.sha256
provenance.json
```

The binary candidate is a 30-day GitHub Actions artifact. The separate `prepare-review` job
revalidates provenance, records it under `candidates/<module>/<version>/`, and opens the predictable
`automation/<module>-v<version>` PR. That job alone has `contents: write` and
`pull-requests: write`; the source-code build job has read-only contents permission and no
production secrets. PRs are never auto-merged.

Candidate provenance is separate because Registry v1 has no builder-provenance fields and a
temporary Actions artifact is not a valid production HTTPS URL. Therefore this phase does not
silently extend the schema or point Registry v1 at an ephemeral download. Permanent hub artifact
hosting and the final reviewed candidate-to-Registry promotion remain a later cutover step.

For an existing Registry version, equal source commit and digest produce `already-registered`;
different provenance fails hard. Candidate files behave the same way. Re-running an identical
request reuses the predictable branch/PR and the first retained Actions artifact reference rather
than creating a conflicting record.

Stable is never implicit: the manual workflow defaults to `beta`, while a `stable` plan must be
selected and remains visible in the PR. No build job changes the production Registry.

## Security, recovery, and future hosting

Building executes source code and currently has network access for locked Python/npm dependency
resolution. The trust boundary is therefore the explicit first-party allowlist; community modules
are out of scope. Checkouts are temporary, commits cannot be overridden, git `file://` transport is
disabled for source fetches, action revisions and tool versions are pinned, and build jobs receive
no Registry or production credentials. GitHub-hosted runner timeouts bound execution.

Recovery is the same manual dispatch with the same module and immutable tag. There is no tag-move,
commit override, digest override, direct production mutation, or artifact overwrite path.

The builder, Actions artifact retention, and candidate/Registry writer are separate components.
Permanent storage can replace the Actions-artifact URI without changing source resolution or
build logic. Only after that promotion path is reviewed should source repositories remove their
existing release workflows, one module at a time. Statistics and Analysis Areas remain the first
pilots; their source-repository workflows are intentionally untouched here.

## Pilot evidence

The implementation was exercised locally against Host commit
`a0ec1edb1c904db18fea78aaffb531407e46f378`, which contains the Analysis Areas migration cutover
and the Statistics public service contract required by both pilots.

| Pilot source | Source commit | Central SHA-256 | Result |
| --- | --- | --- | --- |
| Statistics `v0.4.0` | `3cfce04b859e5f27481f5665adc4665ddc935dac` | `1898fdee9ab2c9f6949eb3f0f0246f058a8ee9aabc48b9c1bab681300821de3e` | two byte-identical builds; lifecycle and `statistics.query` passed; new candidate |
| Analysis Areas `v1.5.1` | `e190c4c5a70df6dbbe1f538f82e68d30260fe071` | `637249c085bbd99b6683afddec7fdd747150d21cb42a75a1a8ede351a41b3a00` | two byte-identical builds; dependency, migrations, public services, disable/re-enable passed; new candidate |
| Analysis Areas `v1.5.3` | `06a675a4237fca397b37c0aeb935ecd60557073a` | `03c678689e89c0e499ab09c5bac758db3e59ef8ab9e089d5da349c31b4e4a6df` | build and Host gates passed; candidate correctly rejected because Registry already binds this version to another digest |

The previous source-repository artifacts have different digests (`4a3201…` for Statistics 0.4.0,
`8fd4b2…` for Analysis Areas 1.5.1, and `88ead4…` for Analysis Areas 1.5.3). This is not treated as
a reproducibility failure across different builders. The central double-build is the reproducible
baseline from Builder-of-Record cutover onward; existing Registry entries remain immutable.
