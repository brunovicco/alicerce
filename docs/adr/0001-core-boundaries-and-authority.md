# ADR 0001: Core Boundaries and Authority

Status: Accepted
Date: 2026-07-18

## Context

Phase 0-1 established canonical contracts and independent, report-only quality
gates. Phase 2 needs orchestration without allowing a builder, model provider,
or observability system to become the authority for technical acceptance.

## Decision

Alicerce will be a provider-neutral orchestration core organized around ports.
It may coordinate candidate creation, execution, evidence, gates, verdicts,
budgets, state, and human-review requests.

Authority is separated as follows:

- `engineering-loop-schemas` owns canonical serialized contracts;
- Alicerce owns orchestration and lifecycle policy;
- provider adapters may build candidates but cannot certify them;
- hard gates independently assess candidates using a trusted, pinned gate
  specification whose driver, protected configuration, acceptance criteria,
  and permitted candidate inputs cannot be replaced by candidate content;
- the verdict builder derives outcomes only from validated evidence and policy;
- humans and external repository workflows retain promotion and merge authority.

The core will not directly import Codex-, Claude-, GitHub-, A2A-, MCP-, or
telemetry-specific domain concepts. Integrations enter through adapters.

## Consequences

- Provider integrations remain replaceable and independently testable.
- The builder cannot approve its own output.
- An external workflow is required to act on an eligible candidate.
- More interfaces and conformance tests are required.
- Schema evolution must occur upstream before new canonical fields are used.

## Rejected alternatives

### Put orchestration in each harness

Rejected because duplicated state, evidence, and policy logic would drift.

### Let the provider return the final verdict

Rejected because self-reported confidence is non-authoritative and cannot
replace mechanical hard gates.

### Include merge and deployment in the initial core

Rejected because it expands authority before isolation, recovery, and human
approval boundaries are proven.

## Acceptance conditions

- Domain modules contain no provider-specific identifiers.
- Tests demonstrate that builder output cannot directly produce `PASS`.
- Tests demonstrate that a gate definition modified inside the candidate
  workspace cannot replace or weaken the trusted gate harness.
- No Phase 2A port exposes merge, deploy, release, or branch-protection actions.
- Canonical serialized artifacts validate against a pinned schemas release.
