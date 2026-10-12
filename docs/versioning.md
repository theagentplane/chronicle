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

- **SemVer from 1.0 (now).** Breaking changes need a new major. Within a major: new optional
  parameters, new settings with a safe default, new adapters and new instrumenters are additive.
  Every change is classified in the [changelog](../CHANGELOG.md) as **compatible** or **breaking**,
  with the migration each consumer needs. Pin `agent-chronicle>=1.0,<2`.
- **Primitives is pre-1.0**, so Chronicle pins it at the exact minor (`==0.1.*`). A primitives
  schema change therefore ships as a Chronicle release that moves the pin, classified like any
  other change.
- **Identity.** `trace_id` is the only run identifier. There is no `run_id`, and none is added;
  consumers key on `trace_id` (ADR 0009).
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

| Change | Version |
|---|---|
| Rename or remove a public name, change a default that alters what is recorded, change what a documented field holds | major, breaking |
| New optional parameter, setting, adapter or instrumenter | minor, compatible |
| New envelope `metadata` key under `chronicle.` | minor, compatible |
| Bug fix with no documented behaviour change | patch |

## Why 1.0

The 0.5 to 1.0 change is the clean break (design decision 14), and the maintainer decided to call the
result 1.0: the public API, the configuration and the documented behaviour are what this version
commits to. Two things are open and are tracked rather than hidden: the control-plane endpoint paths
(confined to `chronicle.repositories.http_endpoints`, so a change there is a patch to that module)
and the `agentplane-primitives` pin, which stays at the exact minor until primitives reaches 1.0.
