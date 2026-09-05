# Immutable OCP Artifact Store

## Audit before implementation

Baseline: `f28415eb7344bd49e7699a4635791161c4d88a6d`. Registry v1 JSON remains
production metadata authority. This is the storage boundary of [ADR #44](adr/registry-service-v2.md)
and [#46](https://github.com/oklabflensburg/open-city-planner-packages/issues/46).

| Existing component | Reuse / change |
| --- | --- |
| `scripts/publish_artifacts.py` | Reuse validated identity/URL derivation, existing-file digest check, same-filesystem atomic no-clobber link and fsync design. Extract storage into one backend used by mirror and local publisher; independently hash copied/stored bytes rather than trusting a downloader's return value. |
| `scripts/verify_artifacts.py` | Keep bounded allowlisted HTTPS download, redirect policy and optional pinned Host verification as intake gates. They do not belong in a filesystem storage backend. |
| Existing mirror/deploy | `--all` still selects reviewed Registry v1 releases during Ansible deployment. Missing self-mirror URLs fail closed. Preserve the CLI/results and append-only batch recovery behavior; #49 later separates the production release lifecycle. |
| Persistent store | `/opt/open-city-planner-packages/artifacts/modules/...` already sits outside application `releases/`. Keep the versioned layout and all historical URLs; no byte migration is needed. |
| Nginx | Existing artifact alias already serves only canonical `.ocp` paths with octet-stream, `nosniff`, immutable one-year cache and no directory listing. Add explicit symlink denial at the serving boundary. |
| Retention | Independent release-retention code only prunes validated release trees. Retain its boundary and verify with a real sibling artifact store. |
| Permissions | Current trusted publisher runs as `ocp-packages`; Nginx reads 0644 files/0755 directories. API/SSR share the service identity but systemd `ProtectSystem=strict` makes their filesystem read-only. Document a dedicated publisher identity as the target provisioning model, without a production account cutover here. |

The v2 interface/CLI accepts an approved local source file and expected digest,
returns storage metadata, and never changes PostgreSQL, Registry JSON, channels or
application deployment state. It does not itself establish human approval.

## Interface and layout

`scripts.artifact_store.ArtifactStore` defines `publish`, `verify`, `exists` and
`public_url`. `FilesystemArtifactStore` implements that contract without importing
DB models, running builds, resolving dependencies or downloading URLs. Its publish
result contains status plus module/version, digest algorithm/value, byte size,
storage locator and public URL. #49 may use these values when linking the #45
Artifact row in a reviewed Registry transaction; this code never opens a DB session.

Configure an explicit absolute root in code or `PACKAGES_REGISTRY_ARTIFACT_ROOT`:

```text
/opt/open-city-planner-packages/
├── releases/<application-sha>/          separate application lifecycle
├── current -> releases/<application-sha>
└── artifacts/                          configured root, independent lifecycle
    ├── .staging/<random-id>.partial     private publisher staging (0700 directory)
    └── modules/statistics/0.4.0/statistics-0.4.0.ocp
```

There is no implicit local or production root. Relative roots, `/`, traversal and
roots containing `releases` or `current` components are rejected. Operators must
also keep custom-named application release directories outside the store; the
library cannot infer arbitrary infrastructure layouts. Existing Ansible root
assertions and release-retention restrictions remain in force.

Public URL format:
`https://packages.stadtplaner.oklabflensburg.de/modules/{id}/{version}/{id}-{version}.ocp`.
No mutable `latest.ocp` or channel-based binary alias is introduced.

The **storage locator is the relative object key**
`modules/{id}/{version}/{id}-{version}.ocp`, independent of machine/root/backend.
Digest and URL are separate fields. Phase 1 retains canonical versioned files;
there is no second content-addressed copy or deduplication namespace. A later S3
backend can implement conditional object creation and verification behind the
same interface. A future `sha256/<prefix>/<digest>` object-key scheme must retain
all existing versioned public URLs and immutable bindings. No OCI protocol,
filesystem metadata registry or sidecars are introduced.

## Trusted local publication

After human approval and candidate validation, invoke the trusted publisher:

```bash
export PACKAGES_REGISTRY_ARTIFACT_ROOT=/absolute/path/to/disposable-artifact-store
scripts/publish-artifact \
  --module statistics --version 0.4.0 \
  --source /absolute/path/to/reviewed/statistics-0.4.0.ocp \
  --expected-sha256 6bec701141f8c77dff4c4054ae095be31efe262f9cc3eab6414f68be57ae5423
```

Equivalent module command: `uv run python -m scripts.publish_artifact ...`.
`--artifact-root` overrides the environment. There is no destination-path argument.
Source filenames are not trusted for identity; the caller supplies reviewed module,
version and expected digest. The store requires a regular, non-symlink source and
validates module ID, exact SemVer and lowercase SHA-256 with Registry validators.
It hashes actual source bytes before creating storage directories or copying data.
Digest verification is mandatory; bundle identity/Host contract and review are
upstream requirements, not fabricated approvals supplied by this low-level CLI.

| Status | Exit code | Meaning |
| --- | ---: | --- |
| `published` | 0 | This publisher installed the complete immutable file |
| `already-present` | 0 | Existing complete bytes match; no overwrite |
| `invalid` | 2 | Invalid identity/digest/source or unsafe path |
| `conflict` | 3 | Existing version bytes differ from the expected digest |
| `storage-error` | 4 | I/O/durability failure; verify state before retry |

Operation results are JSON without source paths, absolute storage roots or raw OS
errors. Argument-parser usage errors also exit 2. A success includes only relative
storage metadata and the modeled public URL; it does **not** prove that production
Nginx has been configured or that this URL is publicly reachable.

## Atomicity, integrity and durability

The backend strengthens the existing mirror's same-filesystem hardlink design:

1. Open every source-directory component using directory descriptors and
   `O_NOFOLLOW`, then open and hash a regular source file. Keep that descriptor
   pinned through the copy; a later symlink replacement cannot redirect it.
2. Open/create root/module/version directories without following symlinks. Fsync
   newly created directories and their parents. Existing permissions are preserved.
3. If the final file already exists, read and compare its complete digest. Matching
   content is an idempotent success; any different digest or non-regular target
   fails. Never unlink or replace the existing version.
4. Create an exclusive random file inside private `.staging` on the same filesystem
   as the final parent. Copy bytes, flush, set final 0644 permissions, fsync the file
   and reread the copy's digest. A changed source or corrupted copy fails before the
   public name exists. Verify that the parent still denotes the opened directory.
5. Use `os.link` with directory descriptors and no symlink following to create the
   public name atomically. A preexisting name is never replaced. If another process
   won, verify that winner's complete digest and return either `already-present` or
   `conflict`. Rehash the final file on every successful publication path.
6. Fsync the final parent, remove the private staging name and fsync staging. The
   final file has no persistent hardlink to the input or temporary file.

See the underlying [Python filesystem API](https://docs.python.org/3/library/os.html)
for descriptor-relative operations and fsync. Guarantees are for a trusted local
POSIX filesystem supporting these operations; they do not claim distributed/NFS
consistency or durability beyond the filesystem/device's fsync behavior. Temporary
intake files may reside on another filesystem: they are copied into store staging
before the atomic link. Staging/final device mismatch is rejected; `EXDEV` is never
handled by a non-atomic copy to the public path.

Failure before the link leaves no public file. A failure or lost response after
linking may leave a complete verified final file even when the caller reports an
error. Do not delete it: verify and retry with the same reviewed source/digest.
Successful retries preserve the file's inode and modification time. Conflicting
retries never replace bytes. Two concurrent same-digest publishers have exactly one
`published` result and one `already-present`; different-digest contenders have one
winner and one conflict. No lock file or sidecar becomes Registry truth.

A process crash can leave private `.staging` files; public routing cannot reach
them. After stopping all publishers, operators may remove abandoned staging files
without touching final artifacts. Do not run background cleanup that races active
publishers. A digest mismatch in a stored version is a storage integrity incident:
quarantine the store for investigation and recover original verified bytes through
a reviewed procedure, never silently "repair" it by overwriting via this API.

## Path and permission boundaries

Directory-descriptor traversal rejects symlinks at the root, ancestors, module or
version directories and final files. Final paths are derived from validated IDs,
versions and digests; encoded traversal, slashes, backslashes and NUL identity
inputs fail. Parent identity/containment is rechecked before publication. These
protections do not authorize hostile users to rename or modify store directories:
only the trusted publisher/administrator may write the root or its ancestors.
A privileged owner can still corrupt a file directly; this API detects such drift
but does not impose kernel immutable flags or defend against an administrator.

The current deployment's `ocp-packages` account is the trusted publisher; Nginx is
the reader and receives no write access. Store files are 0644 and directories 0755,
with private 0700 staging owned by the publisher. Do not share staging between
unrelated publisher UIDs. Application services remain read-only through existing
systemd `ProtectSystem=strict`; no artifact write exceptions are added. Provisioning
a distinct publisher Unix identity instead of sharing the application's account is
the target for a later operational cutover, not an unannounced account change here.

The source-executing central builder receives no storage/production credentials.
Candidate download and human approval precede execution of the trusted publisher.
This PR adds no Source Build → Production job, SSH step or production publish run.

## HTTP serving and health

The existing Nginx alias serves versioned paths directly from `artifacts/modules`,
independent of `current/dist`. Headers remain `application/octet-stream`,
`X-Content-Type-Options: nosniff` and
`Cache-Control: public, max-age=31536000, immutable`, with length/ETag supplied by
Nginx. `autoindex off` and closed artifact route matching prevent directory/partial
exposure. The artifact location now uses
[`disable_symlinks on`](https://nginx.org/en/docs/http/ngx_http_core_module.html#disable_symlinks)
so a filesystem link cannot bypass the publisher boundary during HTTP reads.

`store.health()` requires an existing readable root and changes nothing.
`store.health(publisher=True)` additionally creates/fsyncs/removes a private probe
and checks staging/root device identity. Run the former as the web-reader identity
and the latter as the publisher to test their effective permissions. Each real
publish separately checks staging/final device identity, including nested mount
points. `verify(id, version, expected_digest)` rehashes a selected stored object;
`exists()` checks a safe regular-file presence only and makes no digest assertion.

## Existing mirror and recovery

`scripts/publish_artifacts.py` remains the compatible Registry v1 orchestration
layer: validated Registry selection, bounded allowlisted GitHub download, optional
pinned Host verification, bulk result format and append-only retry are retained.
Download/verification take place in private intake; `FilesystemArtifactStore` is
the single final publication implementation for both old mirror and new CLI.
The store independently checks bytes even if a downloader claims the right digest.

Matching existing artifacts bypass network downloads. Missing canonical self-mirror
references fail closed instead of recursively downloading from the missing store.
For historical recovery, retrieve a known reviewed GitHub Release URL through the
existing bounded downloader, verify its original recorded digest and publish through
this same core. If Registry metadata already points to the missing canonical URL,
recover the original reviewed source from history through an explicit recovery
procedure; never change v1 JSON just to bootstrap a missing object.

The existing deployment still invokes mirroring as before. The new trusted local
publication operation is independently callable without Nuxt/FastAPI rebuild or
Ansible application deploy. #49 owns automatic reviewed promotion and the final
removal of release/deploy coupling. No historical URL, Registry version or channel
is modified by this refactor.

## Backup and restore

Back up the **artifact root independently of application release retention**, keeping
all final `modules/` objects and their original versioned names, permissions and
trusted ownership. Exclude `.staging` from durable backups; it contains no published
truth. The only hardlink is the short-lived staging/public link during publication;
copying final files normally is sufficient, with no cross-root hardlink dependency.
Take a filesystem snapshot or reconcile the copied object inventory against the
recorded DB/Registry backup so concurrent append-only publications are accounted for.

Record expected digests and relative locators from the reviewed v1 snapshot today,
and from the corresponding Registry DB backup after #49. Do not derive expected
checksums from potentially damaged backup bytes. Backups of PostgreSQL alone cannot
recover artifacts, and application rollback/pruning never deletes them.

Restore sequence:

1. Restore bytes to a new offline root, retaining original public-path mappings.
2. Reject symlinks/non-regular entries and verify every referenced object with its
   independently recorded digest using `store.verify`. Missing or mismatching bytes
   block activation; do not expose DB references or invent a replacement digest.
3. Restore/check the corresponding DB metadata or current v1 snapshot and reconcile
   all referenced locators. Retain objects required by older DB backups and clients.
4. Expose the verified root through the configured artifact alias and verify public
   response bytes/headers before enabling Registry reads/promotions.

A corrupt existing root should be replaced operationally with the separately
verified restored root, not overwritten file-by-file by the publish CLI. Root
selection is explicit configuration, never a symlink within the Artifact Store.
There is no automatic object deletion/retention feature in this PR.

## Validation and Statistics pilot

On 2026-09-05, downloaded retained Actions artifact **9963540658**, named
`statistics-v0.4.0`, from
[run 33946623199](https://github.com/oklabflensburg/open-city-planner-packages/actions/runs/33946623199).
The retrieved provenance matches the reviewed
[`candidates/statistics/0.4.0/provenance.json`](../candidates/statistics/0.4.0/provenance.json).
The original candidate file is **28,555 bytes**, SHA-256
`6bec701141f8c77dff4c4054ae095be31efe262f9cc3eab6414f68be57ae5423`.

Published these exact downloaded bytes into an isolated `/tmp` Artifact Store:
first invocation `published`, second `already-present`, with matching size, digest,
relative locator and modeled public URL. No rebuild or synthetic candidate digest
was used. No production URL was published or asserted reachable; no Registry v1
version/channel or PostgreSQL record was added. If retained bytes later expire,
recovery must fail closed or re-establish identical reviewed evidence; generic test
fixtures are not substitutes for this candidate.

Normal CI uses clearly labeled synthetic byte fixtures and real temp filesystems,
including separate-process races, source/copy/final integrity, symlink swaps,
pre-link failure, post-link durability recovery and backup verification. The
Ansible suite uses a private unprivileged Nginx process on loopback with a generated
test certificate and the real rendered template to verify headers, byte serving,
partial-file rejection and symlink denial. It also runs actual release pruning
beside a published store. Neither suite needs production credentials or publishes
production artifacts. Install `nginx` and `openssl` to run the explicit HTTP suite.

```bash
uv run pytest tests/test_artifact_store.py tests/test_artifact_publishing.py
uv run pytest deploy/ansible/tests
```
