# ADR 0006: Optional a2a-otel-kit Adoption

Status: Accepted
Date: 2026-07-18

## Context

`a2a-otel-kit` provides vendor-neutral OTLP export, structured correlation,
W3C Trace Context propagation, deny-by-default sanitization, optional A2A/MCP
integrations, and Collector receipt testing. It also uses an engineering harness
configuration, providing a useful dogfooding path.

Version 0.4.2 is Beta and requires Python `>=3.13,<3.15`. Its generic span API
records exceptions by default, which is inappropriate at boundaries where
exception messages or stacks may contain subprocess or tool content.

## Decision

Adopt `a2a-otel-kit` only as an optional adapter behind `ObservabilityPort`.
The core will not import it, vendor it, or require a Collector.

The initial compatible dependency policy is proposed as:

```toml
a2a-otel-kit>=0.4.2,<0.5
```

The source constraint remains bounded while the generated lockfile records the
exact resolved version. Python 3.12 combinations must be rejected before
generation; Python 3.13 and 3.14 are the supported initial matrix.

The adapter must:

- disable exception recording at content-sensitive boundaries;
- emit only the centrally allowlisted events and scalar attributes;
- obey central sensitivity and exception-recording policy without adapter-level
  relaxation;
- preserve W3C context without copying application payloads;
- support operation without an available Collector under best-effort policy;
- expose typed export failure for required-export policy;
- keep evidence and verdict creation independent of span delivery.

Harness bootstrap integration is deferred until the port and adapter API are
stable. Proposed future CLI semantics separate capability from protocol:

```text
--observability none|otel
--protocol none|a2a|mcp|both
```

`agentic` governance never enables the option automatically. `service` is the
primary supported profile; library and workspace behavior require explicit
dependency-placement rules.

## Consequences

- Alicerce gains an official integration path without mandatory dependencies.
- Python 3.12 remains supported by the core but not by this adapter version.
- Protocol and Collector integration tests remain outside deterministic core
  unit tests.
- A future incompatible kit release requires adapter review.

## Rejected alternatives

### Make the kit a mandatory core dependency

Rejected due to dependency weight, Python compatibility, and operational egress.

### Vendor the kit

Rejected because OpenTelemetry, Pydantic, and structlog do not belong in the
offline stdlib-only schema-validation boundary.

### Install it automatically for agentic governance

Rejected because observability requires explicit choices about configuration,
network, retention, privacy, and cost.

### Add telemetry fields to schemas immediately

Rejected until an implemented adapter demonstrates a stable, necessary,
non-authoritative reference shape.

## Acceptance conditions

- The core and no-op adapter pass without the optional package installed.
- Python 3.13/3.14 tests cover base, A2A, MCP, and combined extras.
- Python 3.12 receives a clear pre-install rejection.
- Collector tests verify actual receipt, not only connectivity.
- Sanitization tests prove prohibited content cannot become telemetry.
- Adapter failure never produces `VERIFY_FAILED`.
