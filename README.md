# Open City Planner Packages

Static package registry for installable [Open City Planner](https://github.com/oklabflensburg/open-city-planner) modules.

This repository is the registry and publishing layer. It contains reviewable module metadata, JSON Schemas, validation and publishing policy, and a deterministic static build. It does **not** contain the Open City Planner runtime, module execution or installer logic, a marketplace, a dependency resolver, or an API server.

The repository currently provides **Registry v1 infrastructure**. The production registry is intentionally empty; no built-in or fake production module is published here.

## Responsibility split

- `open-city-planner`: host, runtime, SDK, `.ocp` v1 bundle reader, verification, installer, and authoritative `modules.lock` state.
- `open-city-planner-packages`: registry source, metadata schema, static index, validation, review policy, and deployable static output.
- Separate module repositories: module source, tests, and immutable `.ocp` v1 releases.

The registry is needed only for discovery and download before installation. An administrator downloads a versioned release, verifies the registry SHA-256, then passes the local file through the host's existing `ocp module verify <file.ocp>` and `ocp module install <file.ocp>` flow. Runtime startup never contacts this registry, and already installed modules continue to work during a registry outage.

## Layout

```text
registry/registry.json       Registry source envelope
registry/modules/*.json     Reviewable module source-of-truth
schema/*.schema.json        Strict Registry v1 schemas
scripts/                    Validation and deterministic build
dist/                       Committed, generated deployment artifact
docs/                       Format, publishing, review, and deployment policy
tests/                      Validator, security, immutability, and build tests
```

Never edit `dist/` manually. It is rebuilt from `registry/` and contains a compact `index.json` plus canonical copies of module metadata.

## Local checks

```bash
uv sync --frozen
uv run ruff check .
uv run pytest
uv run python scripts/validate_registry.py
uv run python scripts/build_registry.py --output dist
git diff --exit-code -- dist
git diff --check
```

To check an existing published baseline for immutable release changes:

```bash
uv run python scripts/validate_registry.py --base-ref origin/main
```

Registry pull requests pass separate gates for metadata/schema policy, published-release immutability, the SHA-256 and official pinned `.ocp` host verifier for every new release, and deterministic static output. Artifact verification streams one release at a time with bounded network access and runs only the host's read-only `verify` command—never `install`.

After first publication, stable module provenance (publisher ID, classification, source repository, and Registry v1 license) is protected, while presentation metadata remains editable through reviewed pull requests.

## Production deployment

The registry has an independent [Ansible deployment](deploy/ansible/README.md)
for `packages.stadtplaner.oklabflensburg.de`. It resolves an explicit Git ref to
an immutable SHA release, rebuilds and validates `dist/`, atomically switches
`current`, serves only `current/dist` through Nginx, and automatically restores
the previous release when rollout smoke checks fail. Production deployment is a
manual, authorized operation after Registry CI; pull requests never connect to
the server.

A contribution adds one file such as `registry/modules/example.json`; see [the format](docs/registry-format.md) and [publishing flow](docs/publishing.md). Registry compatibility fields are discovery metadata copied from the bundle manifest. The embedded manifest remains authoritative during verification and installation.

## Status and scope

Registry v1 is a static data contract for `packages.stadtplaner.oklabflensburg.de`. It introduces no runtime registry client, automatic installation or updates, PKI, dependency solving, module extraction, or second `.ocp`/runtime-manifest format.

Licensed under the GNU Affero General Public License v3.0; see `LICENSE`.
