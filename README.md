# Alicerce

Alicerce is the vendor-neutral foundation for deterministic, auditable,
evidence-gated engineering loops used by Python engineering harnesses.

## Current status

The Phase 2 Design Gate and Phase 2A readiness review are approved. Incremental
implementation of the trusted local core is authorized against the mandatory
Phase 2A acceptance matrix.

The current implementation establishes package boundaries, deterministic
quality gates, canonical schema integration, and immutable run identity types.
It does not implement an autonomous runner, state persistence, candidate
promotion, merge, deployment, provider adapters, or observability integration.

## Architectural direction

- canonical contracts remain owned by `engineering-loop-schemas`;
- evidence and verdict artifacts remain the technical source of truth;
- the shared core remains independent of Codex, Claude, and other providers;
- telemetry is operational context, never authoritative evidence;
- human approval remains required for promotion, merge, and deployment;
- failure handling is explicit, deterministic, resumable, and fail-closed.

The proposed `a2a-otel-kit` integration is an optional observability adapter. It
will not be a mandatory dependency of the core.

## Related repositories

- `brunovicco/engineering-loop-schemas`
- `brunovicco/codex-python-engineering-harness`
- `brunovicco/claude-python-engineering-harness`
- `brunovicco/a2a-otel-kit`

## Implementation scope

Only Phase 2A is authorized. Phase 2B integrations and every repository,
promotion, merge, deployment, and release mutation remain outside the core's
authority.

## Known identity limitation

`RunIdentity` accepts a validated SHA-256 contract digest but does not yet
recompute that digest from canonical contract bytes. Until canonicalization and
hashing are implemented, correspondence between `contract_hash` and the supplied
canonical `Contract` is not mechanically proven. Acceptance rows A03 and A08
therefore remain partial; a strict expected-failure regression test records the
gap and will fail if the limitation is fixed without updating its evidence.
