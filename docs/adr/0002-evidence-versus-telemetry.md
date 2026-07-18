# ADR 0002: Evidence Versus Telemetry

Status: Accepted
Date: 2026-07-18

## Context

Evidence must support deterministic technical decisions. Telemetry supports
operational diagnosis but may be sampled, delayed, unavailable, or deleted by
retention policy. Treating telemetry as evidence would make verdicts dependent
on an unreliable external channel.

## Decision

`evidence.json` and its recorded hashes remain the authority for what ran.
`verdict.json` remains the authority for the derived technical outcome.
OpenTelemetry is non-authoritative operational metadata.

The evidence path may record full command identity and hashed outputs according
to the canonical schema. The telemetry path must use a smaller allowlist and
must not export prompts, responses, stdout, stderr, complete commands, diffs,
paths, evidence payloads, secrets, or personal data.

By default, exporter failure is operationally recorded when possible and does
not change candidate quality. If an organization explicitly requires telemetry
export, failure maps to `INFRA_FAILED` or `ESCALATED`, never `VERIFY_FAILED`.

## Consequences

- Runs remain valid when a Collector is absent under best-effort policy.
- Operational traces cannot reconstruct sensitive evidence content.
- Evidence and telemetry require separate retention and access policies.
- A telemetry backend cannot override or repair a verdict.

## Rejected alternatives

### Use spans as the evidence store

Rejected due to sampling, eventual delivery, backend dependence, and retention.

### Export evidence payloads as span attributes

Rejected because it increases data-egress, privacy, and size risks.

### Fail hard gates when export fails

Rejected because exporter health is infrastructure status, not code quality.

## Acceptance conditions

- Core tests pass with the no-op observability adapter.
- Dropped telemetry does not modify evidence hashes or verdict status.
- Required-export policy has explicit `INFRA_FAILED`/`ESCALATED` tests.
- Attribute tests reject content-bearing and non-allowlisted fields.
