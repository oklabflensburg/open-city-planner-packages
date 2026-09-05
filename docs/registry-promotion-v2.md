# Reviewed Registry v2 promotion

Issue #49 implements the [ADR #44](adr/registry-service-v2.md) trusted publication
boundary. Normal module publication in the **enabled v2 path is a Registry data
operation**. It does not build module source, rebuild Nuxt, restart FastAPI, run
Ansible, prune application releases or create a Registry JSON PR. This PR does not
enable production writers or switch production read routing.

## Audit and reused components

- `scripts/registry_candidate.py` validates allowlisted Central Builder evidence,
  reproducibility and Host contract. Promotion additionally requires a known full
  builder commit and uses existing v1 validation for host/SDK/dependency specifiers.
- `scripts/promote_candidate.py` previously fetched `origin/main`, checked permanent
  artifact hosting and generated a Registry/dist PR or a blocked `promotion-plans/`
  document. This remains **legacy/pre-writer-cutover only**; its manual workflow is
  now `promote-candidate-legacy.yml`, explicitly gated off by default and forbidden
  when the writer-cutover variable is enabled. The script also rejects a declared
  writer cutover. It is not the v2 production release path.
- `FilesystemArtifactStore.publish/verify` supplies #46's digest checking, pinned
  path descriptors, no-clobber publication, fsync durability and canonical URLs.
- `RegistryDatabaseRepository.insert_published_version` now accepts trusted builder
  provenance as well as its original historical-import mode. Both share version,
  compatibility, dependency, immutability and historical-order handling. Historical
  imports still have unknown builder evidence and publication timestamps.
- `validate_v1_representability` from #48 validates the uncommitted future state.
  Existing API reads and content-derived ETags see the commit on the next request.

Statistics 0.4.0 is reviewed evidence in human-merged PR #41, merge commit
`d54085286e5ed0d8df37715b6ed3fca465ee3dbb`, merged by `p3t3r67x0`.
The original run `33946623199`, artifact `9963540658`, was available and downloaded
for the isolated pilot. The builder's historical provenance locator uses
`statistics-0.4.0`, while its upload-artifact name is `statistics-v0.4.0` (module +
source tag). The adapter accepts exactly this documented mapping and verifies run,
workflow, builder SHA, archive provenance, filename, sidecar and actual bundle SHA.
It does not search arbitrary artifact names or accept an expired artifact.

## Approval and trust boundaries

`GitHubCandidateSource` reads the candidate through the GitHub API, never from a
working-tree file or caller-provided Registry payload. It requires:

1. The named PR was merged by a human GitHub user into this Registry's `main` and
   includes the candidate path as an added/modified file. An unrelated PR fails.
2. The candidate at the PR head, merge SHA **and current main** has the supplied
   SHA-256 of `canonical_json(full_candidate)`. This binds every candidate field,
   including module/version, repository/tag/commit, builder, artifact/run reference,
   Host result, compatibility, dependencies and planned channel. A changed candidate
   fails, even if the caller still presents the old approval reference.
3. The requested bundle SHA and channel agree with that reviewed candidate. A
   production dispatch also presents the expected channel revision and idempotency
   key to the protected-environment reviewer. These operational intent fields are
   persisted exactly; changing any of them under an existing key fails.

The candidate approval is the **human merge of the exact PR head content**, not an
unverified `--approval-ref` string or a claim that every PR has an APPROVED review
object. Production execution additionally requires a human-approved protected
`production` environment. The workflow verifies a required-reviewer protection rule
exists; unavailable environment evidence fails closed. Configure reviewers and
prevent self-review in GitHub before enabling the workflow. Main branch protection,
trusted workflow code, runner access and GitHub identities are operational trust
roots; this PR does not weaken or configure them remotely.

The internal service accepts a source adapter for hermetic tests; the CLI offers
no local-JSON evidence override. Recorded public GitHub responses and retained
archive bytes under `tests/fixtures/reviewed-statistics-0.4.0/` are **test-only**.
They do not authorize production when GitHub evidence/retained bytes are unavailable.

## Publication and atomic transaction

`RegistryPromotionService.promote(PromotionIntent, artifact_path)` first verifies
the approved intent, publishes the exact bytes and verifies the final stored digest.
Only then does it open a DB transaction. The store root must be outside application
`releases/current`. No temporary Actions URL becomes public release metadata.

In one transaction:

1. Lock the opaque idempotency key using a transaction advisory lock, then lock the
   module row `FOR UPDATE`. Every promotion uses this order. Hash collisions merely
   serialize unrelated keys. Same-module promotions serialize across channels.
2. Check migration revision, registered module identity/classification, release
   contract and the persisted intent. An exact committed retry returns the original
   result with `status: already-published`, without rewriting any row or pointer.
3. Require the current channel revision to equal the approved expected revision
   (`0` means absent; imported pointers start at `1`). A stale revision fails and
   needs a fresh approved intent; the service never silently rebases it.
4. Bind the Artifact row to actual storage digest/size/locator. Unknown imported
   storage fields may be completed; conflicting known bindings fail. Insert immutable
   version, dependencies and real provenance. Every dependency module must exist;
   specifiers are validated, not resolved. New `published_at` is DB-generated.
5. Set the channel/version and increment revision (or initialize it to `1`), flush,
   validate the full future v1 projection, insert `promotion_events`, then commit.

The `0049_promotions` migration adds only `promotion_events`, keyed by persistent
`idempotency_key`, unique on module/version, with full approved intent, candidate
hash, approval reference/identity, previous/new target, result and commit timestamp.
It is protected by the same ORM immutability guard as published history. A downgrade
refuses to discard committed events. The CLI never runs migrations.

Same key + changed digest/channel/version/approval/revision is a hard conflict.
The same version under a different key also fails; recover the original intent.
Existing immutable version metadata is compared on retry, including provenance.
Retries after a later promotion return the original committed result and **do not
rewind the current channel**. Store publication is reverified on each retry, so
materialized bytes or a still-available approved download are required.

If bytes are missing/wrong or approval fails, no DB transaction begins. If DB access,
validation, dependency insertion, v1 representability, audit insertion or commit
fails, all DB changes roll back. A correctly stored **unreferenced artifact remains**;
never delete it automatically. Retry with the exact intent and bytes. A lost response
after commit is resolved by reading the persistent event on retry, not by guessing
from version existence. No delete/relabel/rollback operation is exposed.

## CLI, roles and workflow

```sh
uv run --extra registry-db python -m web.backend.app.registry_promote \
  --module statistics --version 0.4.0 --channel stable --approval-pr 41 \
  --candidate-sha256 70be3863818e41678fe7c7adeef69edbf865a18d7494a50021cf52e043239626 \
  --bundle-sha256 6bec701141f8c77dff4c4054ae095be31efe262f9cc3eab6414f68be57ae5423 \
  --expected-channel-revision 1 --idempotency-key '<approved-opaque-key>' \
  --artifact-root /srv/registry-artifacts --download-reviewed-artifact --mode staging
```

Alternatively use `--artifact /private/materialized/statistics-0.4.0.ocp` for trusted
retained/recovery bytes; approval and digest verification still apply. No rebuild
fallback exists. Downloads use private temporary directories, bounded ZIP member
sizes and an exact member allowlist; members are read directly, never extracted by
archive paths. Temporary download bytes are removed after the operation; durable
Artifact Store files are retained.

- `registry_reader`: SELECT on Registry metadata/schema revision, no write grants;
  API additionally uses read-only transactions. Runtime holds no artifact write
  permission and no promotion credentials.
- `registry_promoter`: SELECT on Registry tables/schema revision; INSERT on artifacts,
  versions, dependencies, provenance and events; sequence USAGE; UPDATE on channel
  version/revision/timestamp and Artifact size/locator; module SELECT FOR UPDATE
  requires UPDATE privilege on at least one module column (grant `UPDATE(updated_at)`
  if using column grants). No DELETE, DDL or schema-migration ownership. Its Unix user
  alone has Artifact Store write access. Privileged direct SQL is not a supported
  publication interface.
- Migration/import administrators are separate from both runtime and promoter.
  Module source repositories and Central Builder jobs receive neither role.

The CLI reads `PACKAGES_REGISTRY_STAGING_PROMOTION_DATABASE_URL` for staging and
`PACKAGES_REGISTRY_PROMOTION_DATABASE_URL` for production. It never falls back to
the runtime `PACKAGES_REGISTRY_DATABASE_URL`. Production additionally requires
`--confirm-production-promotion` and `PACKAGES_REGISTRY_WRITER_CUTOVER_ENABLED=true`.
Separate databases, OS users and network ACLs enforce environment isolation; a mode
label cannot prove a caller supplied the correct database.

`promote-candidate.yml` is manual-dispatch only, main-only, protected environment,
`contents: read`/`actions: read`/`pull-requests: read`, and a dedicated `[self-hosted, registry-promoter]`
runner with the persistent Artifact Store mount. Pull-request read permission is
needed to verify the merged candidate PR and its changed files. It has no build/source repository
checkout, write API, Registry commit, deployment, cleanup or restart step. Provision
this runner/environment/secret/root explicitly after the read-cutover gates; the
workflow is inactive unless the repository cutover variable is `true`.

## Application deploy separation and recovery

The existing Registry workflow still runs PR and main CI without path exclusions.
A separate classifier uses the exact push before/after SHAs (including every commit
in a push and both sides of renames). Only runtime-relevant `web/`, `deploy/`,
`scripts/`, `schema/`, `config/`, lock/runtime files and deployment workflow changes
make application deployment eligible. Candidate, promotion-plan, documentation and
Registry/dist data-only changes do not deploy. A dispatch performs no Git push.
Failure to classify fails the job; it does not guess a data-only change.

Legacy static publication is now an explicit pre-cutover operation; data-only
merges no longer implicitly deploy its files. Freeze that path before writer
activation. Do not reenable it after DB writes. Application release retention and
its known cleanup failure are unrelated to promotion; neither is called here.

Before first production write, finish #48 read/parity/Host/artifact gates and record
the frozen source, migration, compatible application release and active routing.
Readiness in this code requires `0049_promotions`; stage the additive migration and
compatible readers before writer activation. Keep v2 and public v1 routes DB-backed
across subsequent application deploys. Roll back application code only to a release
supporting this schema and routing; never restore stale static metadata or downgrade
committed audit. Application rollback must not run import, DB restore or channel
mutation. Backup/restore and approved data recovery are separate operations.

After a commit, the version is immutable published history. Never delete it. A future
reviewed channel operation must also pass v1 representability; rolling stable back
to 0.3.0 while 0.4.0 remains historical stable is not representable. Restore a
compatible service/DB using the ADR backup/replay procedure instead.

See [the exact Statistics pilot runbook](promotion-statistics-0.4.0.md). Module-repo
cleanup (`ocp-module-statistics#5`, `ocp-module-analysis-areas#18`,
`ocp-module-search#3`) waits for successful central production cutover; UI #50 is
separate.
