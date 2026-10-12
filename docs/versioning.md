# Versioning policy

Chronicle is imported by user code and read by two other products (the control plane and TokenOps),
so compatibility is a contract and not a courtesy. This policy covers the **Chronicle API**: the
public Python names, the configuration and the behaviour documented in the README. The entity
**schema** (Trace, Span, Envelope) is versioned separately by
[`agentplane-primitives`](https://github.com/theagentplane/primitives/blob/main/docs/versioning.md).

## Two things are versioned

| What | Version | Where |
|---|---|---|
| Chronicle (this package, `agent-chronicle`) | SemVer, `src/chronicle/_version.py` | This document |
| The entity schema | `schema_version` (`major.minor`) on every payload | primitives |

Chronicle pins `agentplane-primitives` at the **exact minor** while primitives is pre-1.0
(`==0.1.*`), and moves to `>=1.2,<2` from primitives 1.0.

## Rules

- **Pre-1.0 (now).** The API may change in a minor release. Every change is classified in the
  [changelog](../CHANGELOG.md) as **compatible** or **breaking**, with the migration each consumer
  needs. Pin the exact minor: `agent-chronicle==0.6.*`.
- **From 1.0.** Breaking changes need a new major. Within a major: new optional parameters, new
  settings with a safe default, new adapters and new instrumenters are additive.
- **What counts as the public API:** the names in `chronicle.__all__`, the `CHRONICLE_*` settings and
  their defaults, the `traceparent` behaviour, and the envelope content Chronicle writes (which
  fields are filled, how `usage` buckets are computed, the reserved `chronicle.*` metadata keys).
  Modules under `chronicle.framework`, `chronicle.repositories` and `chronicle.capabilities` are
  implementation detail unless re-exported from `chronicle`.
- **Release order for a schema change:** primitives, then the control plane (reads both majors),
  then Chronicle and TokenOps (emit the new one).
- **Deprecation:** an API is deprecated for at least one minor before removal, and the changelog
  says so.
- **Control-plane endpoints.** The paths Chronicle calls are in one module
  (`chronicle.repositories.http_endpoints`) behind the `ControlPlaneClient` interface. They are
  agreed with the control plane in its repository; a change there is a Chronicle change in that
  module only.

## Deciding the version of a change

| Change | Pre-1.0 | From 1.0 |
|---|---|---|
| Rename or remove a public name, change a default that alters what is recorded, change what a documented field holds | minor, breaking | major |
| New optional parameter, setting, adapter or instrumenter | patch or minor, compatible | minor |
| Bug fix with no documented behaviour change | patch | patch |
| New envelope `metadata` key under `chronicle.` | minor, compatible | minor |

## Why 0.6 and not 1.0

The 0.5 to 0.6 change is a clean break, but it is not a stable API: the control-plane HTTP endpoints
for span upsert and span reads are not final and primitives is 0.1. 1.0 follows when both are
settled and the end-to-end suite has run against the real control plane.
