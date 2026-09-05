# Open City Planner Packages

**Public package explorer and authoritative Registry v1 source for discoverable, reviewable and verifiable Open City Planner modules.**

[Open City Planner](https://github.com/oklabflensburg/open-city-planner) is an open-source Web GIS and civic-tech platform for urban planning, OpenStreetMap and public-data workflows. This repository provides the **module package registry and publishing layer** for its modular ecosystem.

[![Registry CI](https://github.com/oklabflensburg/open-city-planner-packages/actions/workflows/registry.yml/badge.svg)](https://github.com/oklabflensburg/open-city-planner-packages/actions/workflows/registry.yml)
[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-blue.svg)](LICENSE)

**Registry:** https://packages.stadtplaner.oklabflensburg.de/  
**Open City Planner:** https://stadtplaner.oklabflensburg.de/  
**Main repository:** https://github.com/oklabflensburg/open-city-planner

## What is Open City Planner Packages?

Open City Planner Packages is a static registry for installable Open City Planner modules. It stores reviewable module metadata, strict JSON Schemas, validation rules, publishing policy and deterministic deployment output.

It is designed for a modular open-source GIS ecosystem in which modules can extend an Open City Planner installation without turning the registry itself into a runtime dependency.

The registry provides **Registry v1 infrastructure** and an append-only mirror for reviewed `.ocp` release artifacts. Binary artifacts remain outside Git and outside versioned Registry release trees.

### In scope

- discoverable Open City Planner modules;
- reviewable package and release metadata;
- JSON Schema validation;
- deterministic static registry builds;
- SHA-256 integrity metadata;
- immutable published release records;
- documented module publishing and review workflows;
- deployment of the static registry.

### Out of scope

This repository does **not** contain:

- the Open City Planner runtime;
- module execution or installer logic;
- a database-backed marketplace or write API;
- a dependency resolver;
- automatic module installation or updates.

That separation keeps installed modules independent from registry availability and reduces the security-sensitive surface of the package discovery system.

## How it fits into the Open City Planner ecosystem

| Component | Responsibility |
| --- | --- |
| [`open-city-planner`](https://github.com/oklabflensburg/open-city-planner) | Web GIS host, runtime, SDK, `.ocp` v1 bundle reader, verification, installation and authoritative `modules.lock` state |
| **`open-city-planner-packages`** | Registry source, read-only search API, public package explorer, metadata schema, static index, validation, review policy and deployable package discovery output |
| Module repositories | Module source code, tests and immutable source tags |
| **Central OCP builder** | Allowlisted first-party `.ocp` builds, reproducibility, Host contract and candidate provenance |

A typical installation flow is:

1. discover a module and version in the registry;
2. download the referenced `.ocp` artifact;
3. verify its registry SHA-256;
4. run `ocp module verify <file.ocp>`;
5. install it with `ocp module install <file.ocp>`.

Runtime startup never contacts this registry. Already installed modules continue to work if the registry is unavailable.

## Registry Service v2 architecture

The [Registry Service v2 ADR](docs/adr/registry-service-v2.md) defines the target
architecture for [#36](https://github.com/oklabflensburg/open-city-planner-packages/issues/36):
#44 Architecture → #45 PostgreSQL / #46 Artifact Store → #47 API → #48 v1
compatibility → #49 promotion, with #50 UI consuming the API. It includes the
current-system audit, source-of-truth matrix and gated migration plan. Registry v1
remains authoritative until the documented cutover; this is not a completed migration.

## Why a static registry today?

The package registry intentionally uses reviewable files and deterministic output instead of a dynamic marketplace service. This makes module publication easier to audit and keeps the trust boundary explicit.

The model is useful for civic-tech, municipal GIS and other open-source deployments where reproducibility, provenance and understandable release review are more important than opaque automatic installation.

## Repository layout

```text
registry/registry.json       Registry source envelope
registry/modules/*.json     Reviewable module source-of-truth
schema/*.schema.json        Strict Registry v1 schemas
scripts/                    Validation and deterministic build tooling
dist/                       Committed generated deployment artifact
docs/                       Format, publishing, review and deployment policy
tests/                      Validator, security, immutability and build tests
deploy/                     Reproducible production deployment
web/backend/                Read-only FastAPI/Pydantic Registry API
web/frontend/               Nuxt 4/Tailwind CSS 4 SSR package explorer
```

Never edit `dist/` manually. It is generated from `registry/` and contains a compact `index.json` plus canonical copies of module metadata.

## Publish a module

A contribution typically adds or updates a module metadata file such as:

```text
registry/modules/example.json
```

Before publishing, read:

- [Registry format](docs/registry-format.md)
- [Publishing flow](docs/publishing.md)
- [Documentation](docs/)

Registry compatibility fields are discovery metadata copied from the module bundle manifest. The embedded manifest remains authoritative during verification and installation.

After first publication, stable module provenance such as publisher ID, classification, source repository and Registry v1 license is protected. Presentation metadata can still be changed through reviewed pull requests.

## Local development and validation

Requirements and Python metadata are defined in [`pyproject.toml`](pyproject.toml). The project uses Python 3.12+, `uv`, `pytest`, `ruff` and `jsonschema`.

Run the complete local validation flow:

```bash
uv sync --frozen
uv run ruff check .
uv run pytest
uv run python scripts/validate_registry.py
uv run python scripts/build_registry.py --output dist
git diff --exit-code -- dist
git diff --check
```

The web application is documented in [web/README.md](web/README.md). In short,
run `uv run uvicorn web.backend.app.main:app --reload` from the repository root
and `pnpm dev` from `web/frontend/` in a second terminal.

To validate immutable release history against an existing published baseline:

```bash
uv run python scripts/validate_registry.py --base-ref origin/main
```

Registry pull requests use separate checks for metadata and schema policy, published-release immutability, artifact SHA-256 verification, the pinned Open City Planner `.ocp` verifier and deterministic static output.

First-party source tags can additionally enter the [central Builder of Record](docs/central-builder.md).
Its manual workflow performs two independent builds, a pinned Host lifecycle check, and creates a
review-only candidate PR. It neither auto-merges nor writes the production Registry.

The [cross-run audit and promotion policy](docs/cross-run-reproducibility.md) explains the
enforced build environment, historical candidate checks, and separate promotion workflow.
Promotion remains blocked until reviewed candidate bytes are available at the permanent URL.

Artifact verification processes one release at a time with bounded network access and runs only the host's read-only `verify` command—never `install`.

## Production deployment

The registry has an independent [Ansible deployment](deploy/ansible/README.md) for:

**https://packages.stadtplaner.oklabflensburg.de/**

Pull requests run validation, Ansible policy tests and artifact verification only. After a reviewed merge, a successful push to `main` runs the same validation and Ansible gates before the protected `production` GitHub Environment deploys the exact `github.sha`.

The deployment resolves that SHA to an immutable release, rebuilds and validates
`dist/`, automatically mirrors every missing reviewed `.ocp` release into the
persistent artifact tree, builds the API and SSR frontend from the same SHA,
atomically switches the active release, and verifies the explorer, API, Registry,
and every newly published artifact through the public endpoint.
Rollback and release retention never remove immutable artifacts. The separate
publication playbook remains available for recovery and operations, but normal
reviewed merges require no manual publication step.

## Contributing

Contributions are welcome, especially around:

- module metadata and package discovery;
- JSON Schema and registry validation;
- documentation;
- reproducible builds;
- supply-chain security;
- package provenance and integrity;
- deployment automation;
- developer experience for module authors.

For changes to an existing published release, keep the append-only and provenance rules in mind. Open an issue before making larger changes to Registry v1 semantics or its trust model.

See also the wider [OK Lab Flensburg GitHub organization](https://github.com/oklabflensburg) and the [Open City Planner contributor guide](https://github.com/oklabflensburg/open-city-planner/blob/main/CONTRIBUTING.md).

## Related projects

- [Open City Planner](https://github.com/oklabflensburg/open-city-planner) — open-source Web GIS host and runtime
- [OCP Analysis Areas module](https://github.com/oklabflensburg/ocp-module-analysis-areas) — example of the growing module ecosystem
- [OK Lab Flensburg](https://github.com/oklabflensburg) — civic-tech and open-data projects from Flensburg, Germany

## Keywords

Open City Planner · Web GIS · GIS · civic tech · open data · OpenStreetMap · modules · plugins · package registry · geospatial · urban planning · JSON Schema · supply-chain security · reproducible builds · Python

## Status and scope

Registry v1 remains the static authoritative data contract for `packages.stadtplaner.oklabflensburg.de`. The read-only API and explorer do not introduce automatic installation or updates, PKI, dependency solving, module extraction or a second `.ocp`/runtime-manifest format.

## License

Licensed under the **GNU Affero General Public License v3.0**. See [`LICENSE`](LICENSE).
