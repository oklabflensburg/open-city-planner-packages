# Cross-run reproducibility and reviewed promotion

## Artifact audit: Statistics v0.4.0

Compared the retained local pilot `.ocp` (SHA-256
`1898fdee9ab2c9f6949eb3f0f0246f058a8ee9aabc48b9c1bab681300821de3e`)
against the downloaded candidate from Actions run **33946623199** (SHA-256
`6bec701141f8c77dff4c4054ae095be31efe262f9cc3eab6414f68be57ae5423`).
Both resolve tag v0.4.0 to `3cfce04b859e5f27481f5665adc4665ddc935dac`.

| Component | Local pilot | CI candidate |
| --- | --- | --- |
| Embedded module.yaml | `0e5f7b8335009bfb84fc2222c49a1b2c2cbdb4f5e7e2a9a7e760850ea945dd84` | identical |
| Backend wheel | `30c1805fdfacaab9e2077c350f7331dd1f8080636627bb25f87a02b002f03c9a` | `48c9d3691b8b2746686c54b78e061f2b72040426ccac2b7b950ee187288f2295` |
| Frontend tgz | `1d8e7ba9ab804a1795031cd0bef4a6534c309b925d1ac47c0bab14a7f241f801` | identical |
| checksums.json | `d7364383bce99a20358d7eb03e201dff8addbc498ec479b76a92b2efa0cd0be0` | `220e703ce54ffc4f5067e588d55221345ff53d3bbb703adc5b9bfc0c58e1e761` |

Every uncompressed wheel member is byte-identical, including METADATA, WHEEL, and RECORD.
Member order, timestamps and compression sizes agree. Exactly 19 wheel members differ in ZIP
`external_attr`: local `0o100664 << 16`, CI `0o100644 << 16`. These are the 16 Python source
files plus dist-info/WHEEL, entry_points.txt and top_level.txt. Copying only those corresponding
central-directory attributes from the CI wheel into an in-memory copy of the pilot wheel
produced **exactly the original CI wheel bytes**. This diagnostic did not alter any artifacts.

The local parent process had umask `0002`; the missing umask control allowed checkout and
setuptools-created files to retain group-write permission. CI uses the 0644 result. Source
contents, lockfiles, frontend generation, gzip/tar metadata, embedded source metadata and host
bundling are not responsible for this pair's difference. checksums.json and the compressed outer
ZIP change as a consequence of the wheel bytes. No timestamp, run ID or temporary path differs
inside either artifact.

Both used Python 3.12.14, uv 0.12.5, Node 22.22.3 and the source-selected pnpm 11.22.0 (the
machine-wide pnpm default is not authoritative). Host commit is
`a0ec1edb1c904db18fea78aaffb531407e46f378`. The original pilot ran before its working changes were
committed, so its recorded builder commit is not an exact code attestation. CI used
`e406fb2267e7e28eaba2f7e8384a876e9e10a2f8`, Ubuntu 24.04 image 20260831.293.1. Those distinctions
do not explain the byte drift: the permission-only comparison and corrected builds isolate it.

Use `scripts/compare-ocp left.ocp right.ocp` to report nested file lists, per-file SHA-256,
ZIP attributes, manifest changes, wheel differences and frontend tar/gzip metadata without
extracting executable code.

## Deterministic environment and v1 semantics

All builder subprocesses now use umask 0022, UTC, C.UTF-8 and PYTHONHASHSEED=0. This includes
Git checkout, uv build, pnpm scripts and the Host bundler. No wheel rewrite is performed.
`config/builder-environment.json` pins and enforces the Python, uv, Node and effective pnpm
versions. Candidate provenance adds the actual Host/builder commits, lockfile hashes, bundle
format, zlib, OS, architecture and runner-image identifier. Run IDs remain separate provenance.

Builder v1 intentionally remains v1: archive layout, compression settings, frontend assembly and
embedded workflow metadata are unchanged. We now enforce the environment that produced the
existing CI candidate. The old local umask-0002 pilot is not a conforming v1 reference. Future
layout, normalization or embedded-metadata changes must explicitly review artifact semantics
and version the builder when its output changes for the same declared environment. Recording
zlib/runner versions does not assert universal reproducibility across all future compression
implementations; historical digest checks reject any newly observed drift.

Two independent Statistics orchestrator invocations, each with two fresh source checkouts,
now produce `6bec701141f8c77dff4c4054ae095be31efe262f9cc3eab6414f68be57ae5423`, exactly matching
the existing CI candidate. Both passed Host lifecycle and public-service verification.

Analysis Areas v1.5.1 was likewise built through two separate orchestrator invocations (four
complete builds). All produced
`85f6713d7f06ed275bf912087e53e455b8d057fd857459e95fc9c4cc997c2c07`
and passed Host contracts. Its old umask-0002 pilot digest was `637249c0…`; no historical
Registry or candidate record was rewritten. Analysis Areas v1.5.3 was not rebuilt or promoted.

Repeat with `uv run python -m scripts.check_cross_run --module statistics --tag v0.4.0
--host-root _host-verifier` (or analysis-areas/v1.5.1). This runs separate processes and temporary
trees under differing inherited umasks (0002 and 0077), then compares the outer artifact and its
nested wheel/frontend contents and metadata. Failed builds or different bytes return failure.

Before emitting candidate files, the builder compares its digest/source/builder version with
local candidates, reviewed main, and the corresponding remote automation branch. A mismatch
fails before upload/PR preparation, even for unpublished versions. A later builder commit or
run ID alone does not replace an existing candidate when immutable provenance agrees.

## Promotion and hosting boundary

`scripts/promote-candidate --module statistics --version 0.4.0` fetches candidate provenance
from origin/main. An open PR or a local candidate file is not approval. The separate manual
`promote-candidate.yml` workflow runs only on main, executes no module source, and has only
contents/pull-request write permissions. It creates a draft review PR; it never auto-merges.

The channel, digest, source identity and compatibility come from the reviewed candidate.
The artifact URL is derived from the canonical packages-domain path, never user input or an
Actions URI. Before modifying Registry v1, the CLI downloads that permanent URL using the
existing bounded downloader and verifies its SHA-256. It appends the release, preserves history,
checks immutability and invokes the existing dist generator. Identical promotions are no-ops;
conflicts fail closed.

Permanent hosting of a centrally built Actions candidate is still a separate operational step.
This change does not upload to production or pretend the Actions URL is permanent. With
`--prepare-blocked`, a missing canonical artifact (HTTP 404) produces only a reviewable
`promotion-plans/<module>/<version>.json` in a draft PR. No Registry/dist change is made.
Network failures and digest conflicts remain errors. An existing differing promotion branch
requires explicit review rather than automatic replacement.

At the time of this experiment PR #41 was unmerged and therefore not approved.
At the [v2 ADR audit baseline](adr/registry-service-v2.md), #41 is merged and its
candidate is present in main; Statistics 0.4.0 is still absent from Registry v1.
After candidate review, permanent immutable hosting must be established and the promotion
workflow rerun; then reviewers can merge the Registry PR through existing CI and deployment.
No change here mutates Analysis Areas 1.5.3, PR #41, historical digests or source tags.

Statistics dry-run evidence: the new candidate's permanent URL returned HTTP 404. Promotion
raised `PromotionBlocked` before changing Registry data; no dist was generated. The happy path
is covered with temporary Registry/main-review fixtures and a verified-download test double,
including stable 0.3.0 → 0.4.0, retained 0.2.0/0.3.0 history and an identical second-run no-op.
This is not a claim that production hosting or the actual cutover has happened.
