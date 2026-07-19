# Alicerce

Alicerce is the vendor-neutral foundation for deterministic, auditable,
evidence-gated engineering loops used by Python engineering harnesses.

## Current status

The Phase 2 Design Gate and Phase 2A readiness review are approved. Incremental
implementation of the trusted local core is authorized against the mandatory
Phase 2A acceptance matrix.

The current implementation establishes package boundaries, deterministic
quality gates, canonical schema integration, immutable run identity types, and
exact-byte contract binding. It does not implement an autonomous runner, state
persistence, candidate promotion, merge, deployment, provider adapters, or
observability integration.

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

## Contract identity

`RunIdentity` accepts a `BoundContract` derived from exact UTF-8 JSON bytes. The
binding includes the canonical `Contract`, the original bytes, and their
SHA-256 digest; direct construction revalidates their correspondence. A03
remains partial until persistence and resume are implemented. A08 remains open
until evidence integrity bindings are implemented.
