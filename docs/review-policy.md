# Registry review policy

Every release receives the same Registry v1 data validation and the same host-owned `.ocp` verification. `classification` is publishing metadata, never a runtime trust grant.

Stable approval requires four green, independent gates: metadata/schema policy, published-release immutability, downloaded artifact SHA-256 plus the pinned host verifier, and deterministic static build output. The artifact gate checks all new `stable`, `beta`, and `nightly` releases identically. An unreachable artifact or technically unavailable verifier fails closed.

## First-party stable

- The canonical source repository is public under the controlled `oklabflensburg` GitHub organization.
- Module tests and release CI are green and reviewable.
- The artifact is an immutable, versioned `.ocp` v1 release on an allowed host.
- The pinned host verifier accepts the downloaded bundle.
- SHA-256 over the entire downloaded file matches the registry entry.
- A valid SPDX license identifier is preferred and the declared license matches the source/release.
- ID, version, publisher, source commit/tag, and compatibility mirror the bundle.

## Reviewed-community stable

- Publisher identity and source provenance are understandable and explicitly reviewed.
- The source repository is public and reviewable; the license is present and compatible with distribution.
- Module CI evidence and the exact source commit are available.
- Bundle structure, manifest, backend wheel, frontend archive, and checksums pass the same pinned host verifier.
- Review finds no unexpected network/download/install hooks or metadata-driven shell commands.
- The versioned GitHub Release URL or controlled hosted copy is immutable and its SHA-256 matches.
- Maintainer contact may be recorded in the pull-request discussion when useful, not as registry workflow state.

Git history and pull-request approvals are the audit trail. Registry metadata therefore contains no `reviewed_by`, approval history, account/authentication fields, mutable workflow state, secrets, private token URLs, or trust bypasses. This is a focused release review, not an antivirus platform or organizational governance engine.

## Immutability

Existing module/version release objects cannot be edited or removed after publication, including channel, URL, digest, provenance, and compatibility metadata. Corrections require a new SemVer release. CI compares pull-request source with the base branch and rejects mutations while allowing new versions. Convenience channel pointers in the generated index may advance because they are derived from immutable releases.

Reviewers must distinguish presentation updates from provenance changes. `name`, `description`, `homepage`, `documentation_url`, and `publisher.name` are controlled mutable presentation fields. Published `id`, `publisher.id`, `classification`, `source_repository`, and Registry v1 `license` are protected. A legitimate transfer, reclassification, or license-model change needs a separate explicit policy/migration review; no normal metadata PR can override these protections.
