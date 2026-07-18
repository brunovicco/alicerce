# ADR 0003: Observability Port

Status: Accepted
Date: 2026-07-18

## Context

Phase 2 requires structured operational correlation without coupling the core to
OpenTelemetry libraries, a Collector, or a specific vendor. Core tests must be
deterministic and usable offline.

## Decision

The domain will depend on a minimal `ObservabilityPort`. The first shipped
implementation will be `NoopObservability`; it performs no network access and
requires no optional package.

The port conveys event name plus pre-sanitized scalar attributes. It does not
accept arbitrary objects, exceptions, logs, evidence documents, or subprocess
output. Event names and attribute keys are centrally allowlisted.

A central observability policy, rather than each adapter, owns event names,
attribute allowlists, sensitivity classification, cardinality limits, context
propagation, and permission to record exceptions. Adapters may enforce stricter
handling but cannot relax the central policy.

Initial event vocabulary:

- `loop.run.started`;
- `loop.workspace.prepared`;
- `loop.builder.started`;
- `loop.command.completed`;
- `loop.gate.completed`;
- `loop.budget.exceeded`;
- `loop.verdict.decided`;
- `loop.human_review.requested`;
- `loop.run.completed`.

An optional adapter may later delegate to `a2a-otel-kit`. Sensitive execution
boundaries must disable exception recording. Adapter errors are returned or
classified through explicit policy; they are never silently converted into a
candidate verification failure.

## Consequences

- The core has no mandatory OpenTelemetry dependency.
- Offline and failure-path tests remain deterministic.
- Adapter authors must translate richer backend APIs into the narrow port.
- Event vocabulary becomes a compatibility surface and needs conformance tests.

## Rejected alternatives

### Import `a2a-otel-kit` directly in domain modules

Rejected because it would introduce OpenTelemetry, Pydantic, and structlog into
the mandatory core and constrain supported Python versions.

### Pass exception objects through the port

Rejected because exception messages and stacks can contain tool output, paths,
prompts, credentials, or personal data.

### Enable observability automatically for agentic projects

Rejected because telemetry creates dependencies, egress, retention, and
operational responsibilities that require explicit consent.

## Acceptance conditions

- Importing and running the core requires no observability package.
- No-op execution performs no network or filesystem telemetry writes.
- Attribute validation is deny-by-default.
- Tests prove adapters cannot enable exception recording for a boundary the
  central policy classifies as content-sensitive.
- Adapter failures follow configured best-effort or required-export policy.
- Content-sensitive spans use exception recording disabled.
