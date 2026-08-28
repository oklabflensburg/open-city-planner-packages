# Registry format v1

Registry v1 is a strict, static JSON data contract. Unknown schema versions and unknown fields fail validation; there is no migration engine. `registry/registry.json` declares `schema_version: 1`, while each reviewable `registry/modules/<module-id>.json` file contains one module and all of its releases. The canonical ID is the host's lowercase kebab-case module ID, not a registry-specific identity.

## Module metadata

```json
{
  "schema_version": 1,
  "id": "energy-analysis",
  "name": "Energy Analysis",
  "description": "Spatial energy analysis module.",
  "publisher": { "id": "oklabflensburg", "name": "OK Lab Flensburg" },
  "classification": "first-party",
  "source_repository": "https://github.com/oklabflensburg/energy-analysis",
  "license": "AGPL-3.0-only",
  "versions": [
    {
      "version": "1.4.0",
      "channel": "stable",
      "artifact": {
        "url": "https://github.com/oklabflensburg/energy-analysis/releases/download/v1.4.0/energy-analysis-1.4.0.ocp",
        "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
      },
      "bundle_format_version": 1,
      "source_commit": "0123456789abcdef0123456789abcdef01234567",
      "source_tag": "v1.4.0",
      "requires": {
        "host": ">=0.2.0,<1.0.0",
        "sdk": ">=1.7.0,<2.0.0",
        "modules": {}
      }
    }
  ]
}
```

`publisher.id` is stable metadata; it is not an account. The allowed public classifications are `first-party` and `reviewed-community`. Both receive identical technical validation, and classification never bypasses host security.

Versions are complete SemVer. Each `id + version` is unique and immutable once published. Channels are `stable`, `beta`, and `nightly`; v1 implements no promotion service. `stable` releases use non-prerelease SemVer. A channel pointer may move to a newer release, but old release metadata remains unchanged.

The artifact digest is exactly SHA-256 over the complete `.ocp` file: 64 lowercase hexadecimal characters. `source_commit` follows the host provenance contract and is a 40- or 64-character lowercase hexadecimal Git object ID. URLs are HTTPS without credentials, query tokens, or fragments. Artifact URLs must be versioned `.ocp` paths on the controlled registry host or GitHub Releases; first-party GitHub source and artifacts remain under `oklabflensburg`.

`requires.host`, `requires.sdk`, and `requires.modules` mirror the embedded module manifest only for discovery, filtering, display, and publishing review. They do not replace it. During installation the `.ocp` manifest and the host compatibility checks are authoritative, and the registry does not resolve dependencies.

## Generated index

`dist/index.json` lists modules sorted by ID. Each channel contains only the highest version and its immutable digest, plus a link to the complete canonical metadata under `/modules/<id>.json`. The actual installation reference remains module ID, version, and digest—not a mutable “latest” value.

Build output uses sorted keys, two-space indentation, UTF-8, one final newline, sorted IDs and versions, and no timestamps or machine paths. Identical source produces byte-identical output. The machine-readable contracts are `schema/module-v1.schema.json` and `schema/registry-v1.schema.json`.

Schema v1 is intentionally closed. New fields require a reviewed additive schema change when compatible, or schema v2 for a breaking contract; consumers must never silently ignore unknown fields.
