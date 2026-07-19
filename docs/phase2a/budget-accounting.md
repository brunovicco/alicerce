# Phase 2A Budget Accounting

Status: Proposed

## Model

Budget accounting separates trusted counters, conservative reservations, and
externally reported usage.

### Directly enforced

- monotonic wall-clock deadline;
- command count reserved before process creation;
- executor output-size safety ceilings;
- provider call count when enabled.

### Reserved before provider work

Before a provider call, the core reserves the maximum permitted token and cost
allowance exposed by the request policy. A call cannot start if its reservation
would exceed the remaining budget.

### Reconciled after provider work

Actual tokens and cost reported by a provider are advisory unless corroborated
by a trusted gateway or meter. Reconciliation follows conservative rules:

- missing or delayed usage charges the full reservation;
- trusted actual usage below reservation releases the difference;
- actual usage above reservation charges the actual amount and blocks further
  work when the ceiling is reached;
- understated or malformed usage never increases available budget;
- counters are monotonic and replay-safe.

`ProviderPort` returns a typed `UsageObservation` containing `source_id`,
`request_id`, token counts, cost, and observation time. It does not return a
trusted boolean. A run-pinned `UsageTrustPolicy` maps known source identities to
`advisory` or `corroborated`; unknown sources are advisory. Only corroborated
observations may release unused reservation. The policy and its hash are part
of immutable run identity, and adapters cannot alter their classification.

Captured-output size is an executor safety limit, not a canonical contract
budget in schemas v0.1.2.

## Deterministic fake provider

Phase 2A includes only a fake provider capable of returning:

- exact usage;
- lower or higher actual usage than reserved;
- missing usage;
- delayed usage;
- malformed or understated usage;
- timeout and typed infrastructure failure.

The fake cannot certify candidate quality or mark its own usage corroborated.
Tests that exercise reservation release must inject an explicit trusted-meter
source and matching `UsageTrustPolicy`; trust is never granted by omission.

## Failure semantics

- exhausted contract budget: `BUDGET_EXCEEDED`;
- provider infrastructure failure before candidate assessment:
  `INFRA_FAILED`;
- ambiguous accounting or unsafe recovery: `ESCALATED`;
- candidate verification failure remains `VERIFY_FAILED`.

## Acceptance criteria

- Concurrent reservations cannot oversubscribe a budget.
- Retries with the same idempotency key do not double-charge.
- Missing usage cannot release reserved capacity.
- Wall-clock uses a monotonic clock.
- Command budget is checked before subprocess creation.
- Every exhaustion path is covered by deterministic tests.
- Unknown and self-asserted sources cannot release a reservation.
- Changing usage trust policy invalidates resume for an existing run.
