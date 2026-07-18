# Alicerce

Alicerce is the vendor-neutral foundation for deterministic, auditable,
evidence-gated engineering loops used by Python engineering harnesses.

## Current status

The repository is in the Phase 2 Design Gate. Its current deliverables are
architectural decisions and interface proposals only.

No autonomous runner, candidate promotion, merge, deployment, provider adapter,
or observability integration is implemented or authorized yet.

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

## Implementation gate

Phase 2 implementation must not begin until the architectural proposal and its
ADRs have been reviewed and accepted.
