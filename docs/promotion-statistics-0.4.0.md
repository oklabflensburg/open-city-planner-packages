# Statistics 0.4.0: isolated pilot and production runbook

**Production promotion: no. Runtime cutover: no.** The implemented path was tested
with the original reviewed bundle in disposable PostgreSQL 18.6 and an isolated
Artifact Store. No production Host, DB, artifact store, SSH or deployment was used.

| Binding | Exact value |
| --- | --- |
| Candidate | `candidates/statistics/0.4.0/provenance.json` |
| Human-merged approval | [PR #41](https://github.com/oklabflensburg/open-city-planner-packages/pull/41) |
| Candidate merge SHA | `d54085286e5ed0d8df37715b6ed3fca465ee3dbb` |
| Canonical full candidate SHA-256 | `70be3863818e41678fe7c7adeef69edbf865a18d7494a50021cf52e043239626` |
| Source tag | `v0.4.0` |
| Source commit | `3cfce04b859e5f27481f5665adc4665ddc935dac` |
| Builder commit | `e406fb2267e7e28eaba2f7e8384a876e9e10a2f8` |
| Bundle SHA-256 | `6bec701141f8c77dff4c4054ae095be31efe262f9cc3eab6414f68be57ae5423` |
| Original run / retained artifact ID | `33946623199` / `9963540658` |
| Actual upload name | `statistics-v0.4.0` |
| Bundle size | 28,555 bytes |
| Historical/current channel | `stable` |
| Public URL | `https://packages.stadtplaner.oklabflensburg.de/modules/statistics/0.4.0/statistics-0.4.0.ocp` |

The isolated result is versions `0.2.0, 0.3.0, 0.4.0`, stable `0.3.0 → 0.4.0`,
channel revision `1 → 2`, one durable artifact and one persistent promotion event.
The existing running API client observes all four endpoints immediately after the
commit, without rebuilding or restarting any application. Exact retry returns
`already-published` and leaves the database unchanged. Real pinned Host selection,
metadata/digest binding, install preflight, installation and compatibility/dependency
enablement pass. Real isolated Nginx serves these original bytes with 200 and
immutable cache headers; metadata/artifact routes remain distinct.

The archive and public GitHub evidence are retained as **test fixtures**, so CI can
exercise this pilot without live GitHub/production calls. Production always reloads
GitHub review/main and artifact evidence. Availability on 2026-09-05 does not
promise future retention; expired/missing bytes block promotion. Never rebuild and
assume the digest will match. Reviewed recovery with identical bytes is separate.

## Production steps — perform only after recorded gate approval

1. Freeze Registry JSON publication and all legacy publication workflows. Record the
   final reviewed Registry SHA; no independent JSON and DB writers may coexist.
2. Import that final source using separate import credentials, migrate to
   `0049_promotions`, and run `registry_verify_v1 --dist /frozen/sha/dist` with reader
   credentials. Require exact parity for all existing modules and the index.
3. Verify every historical artifact's retained bytes/digest and backup/restore
   evidence under #46. Missing historical bytes block cutover.
4. Deploy the compatible DB read service once. Configure a separate reader role and
   enable v2 API plus v1 compatibility. Verify loopback `/health` and `/ready`.
5. Explicitly enable public DB v1 routing using #48's separate Ansible routing flag.
   Record and preserve these flags for all subsequent application deploys/rollbacks.
6. Verify public old state: Statistics stable 0.3.0, all historical versions/bytes,
   API/v1 agreement, `no-cache`, ETags/304 and failure-without-static-fallback.
7. Retrieve original retained reviewed Statistics 0.4.0 bytes. The CLI's
   `--download-reviewed-artifact` checks run, workflow, builder SHA and exact archive
   contents. If unavailable, stop; do not rebuild. A reviewed, exact local recovery
   artifact can instead be supplied with `--artifact`.
8. Reconfirm both hashes in the table. Read the current channel revision; `1` is
   valid only if the imported pointer is still unchanged. Human approval must cover
   the candidate, stable channel, expected revision and unique idempotency key.
9. Configure the dedicated promoter role/runner and protected `production`
   environment with required human reviewers. Confirm all read-cutover gates in
   the ledger, then explicitly set `PACKAGES_REGISTRY_WRITER_CUTOVER_ENABLED=true`.
   Keep `PACKAGES_REGISTRY_LEGACY_JSON_PUBLICATION_ENABLED` false. Supply the private
   promotion DB URL and persistent Artifact Store root; source builders get neither.
10. Dispatch `promote-candidate.yml` with the exact bindings above, revision and key.
    Alternatively use the documented trusted CLI with `--mode production
    --confirm-production-promotion`. It publishes/fsyncs/verifies the artifact
    **before** the transaction, then inserts version/dependencies/provenance,
    advances the pointer, checks v1 representability and commits the audit atomically.
11. Verify `/api/v1/modules/statistics` reports `stable_version: 0.4.0` and
    `/api/v1/modules/statistics/versions/0.4.0` returns the reviewed provenance.
12. Verify `/index.json` reports stable 0.4.0 with the exact bundle digest and a new
    content-derived ETag.
13. Verify `/modules/statistics.json` retains old entries exactly and adds 0.4.0
    with immutable historical `channel: stable`, original source and requirements.
14. Verify the public canonical `.ocp` URL returns 200, 28,555 bytes, the table's
    SHA-256 and `public, max-age=31536000, immutable`. No Actions URL is metadata.
15. Run an isolated real Host install smoke test against public read metadata and
    the verified bundle, including expected-digest and compatibility checks. Do not
    change an existing production Host installation as an incidental smoke test.
16. Record promotion ID/key, approval, source/candidate/bundle digests, previous/new
    target, revision, artifact locator, API/Host results and commit timestamp in the
    cutover ledger. Retain backups independently of application releases.

## Failure and recovery

Before commit, the DB remains old; a verified orphan artifact is safe to retain.
Fix the failed prerequisite and retry the **same** intent/key. After a lost response,
retry returns the committed event; it does not republish metadata. A stale revision
requires fresh review, not changing the revision silently under the old key.

After commit, never delete Statistics 0.4.0 or point at stale static JSON. A channel
rollback to 0.3.0 would fail the unchanged v1 selection guard. Pause promotion and
recover a compatible DB-backed service using backup/replay. An application rollback
must retain the live Registry DB and artifact root and must support migration 0049;
it must never restore Registry data as part of application-release cleanup.
