# Phase 2A Acceptance Matrix

Status: Proposed

Every row is mandatory before Phase 2A can be declared complete.

| ID | Capability | Required evidence |
| --- | --- | --- |
| A01 | Provider-neutral domain | Source scan and import tests show no provider or telemetry SDK identifiers. |
| A02 | Canonical schemas | Full source commit is pinned and serialized artifacts validate against v0.1.2. |
| A03 | Immutable run identity | Mutation and resume tests reject changed contract, baseline, or policy identity. |
| A04 | Isolated workspace | Builder cannot write trusted checkout, state store, artifact store, or gate drivers. |
| A05 | Trusted gates | Candidate gate and threshold tampering is inert. |
| A06 | Pre-spawn policy | Denied command, action, path, environment, and network requests fail before spawn. |
| A07 | Process control | Timeout terminates the process tree and produces a typed result. |
| A08 | Evidence integrity | Candidate SHA, specification hash, outputs, and environment are deterministically bound. |
| A09 | Verdict authority | Builder output cannot directly produce PASS or a final state. |
| A10 | Single assignment | Concurrent or repeated verdict writes cannot produce conflicting verdicts. |
| A11 | Recovery | Resume revalidates identities, hashes, counters, deadlines, idempotency, and prepared review bundles. |
| A12 | Final states | Tests cover all eight canonical states and typed causes. |
| A13 | Stall semantics | Repetition is an internal signal and never overrides typed failure cause. |
| A14 | Budgets | Tests cover reservation, reconciliation, missing and understated usage, unknown sources, and explicit trusted-meter policy. |
| A15 | Retention | Quota, cleanup, traversal, active-run, protected-evidence, and full-storage tests pass. |
| A16 | No-op observability | Mandatory core works offline with no telemetry package or network activity. |
| A17 | Local human review | Verdict and request publish atomically; every crash boundary resumes idempotently or fails closed. |
| A18 | Compatibility | Full quality matrix passes on Python 3.12, 3.13, and 3.14. |
| A19 | Authority ceiling | No port or adapter exposes merge, deploy, release, or branch-protection mutation. |
| A20 | Distribution | Wheel and sdist build reproducibly and contain no candidate/run artifacts. |

## Quality gate

The implementation quality gate must include, at minimum:

```text
lock
lint
format
typing
tests
security
dependencies
architecture
```

Required unavailable gates fail closed. Coverage thresholds and security severity
policy must be protected trusted configuration.

These repository quality gates validate Alicerce itself. They are distinct from
the contract-addressable candidate-gate vocabulary in `trusted-gates.md`, even
where names overlap.

## Completion rule

Phase 2A completes only when every row has reproducible local and CI evidence.
A partial vertical slice may merge incrementally, but it cannot be described as
Phase 2A complete or enable Phase 2B integrations.
