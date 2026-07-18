# ADR 0004: Command Execution and Isolation

Status: Accepted
Date: 2026-07-18

## Context

Command execution is the highest-risk Phase 2 boundary. It can mutate source,
read secrets, access networks, exceed budgets, or contaminate the trusted
baseline. Deterministic evidence requires a controlled and inspectable result.

## Decision

Every candidate runs in an isolated worktree or equivalent disposable workspace
bound to an immutable baseline SHA. The trusted checkout, evidence store, and
orchestrator configuration are not writable by builder tools.

Commands are represented as argv, not shell strings. Implicit shell execution,
shell expansion, inherited aliases, and interactive prompts are disabled. Each
execution specifies:

- allowlisted executable and action classification;
- normalized working directory inside the candidate workspace;
- minimal allowlisted environment;
- timeout and termination grace period;
- stdout and stderr size ceilings;
- network policy;
- budget reservation and accounting;
- stable result fields and output hashes.

Scope and denied-action checks run before execution. Workspace changes are
rechecked after builder activity and before gates. Timeout, cancellation, and
process-tree cleanup must be explicit.

## Failure classification

- candidate command or gate exit failure: eligible for `VERIFY_FAILED`;
- forbidden path or action: `POLICY_BLOCKED`;
- exhausted configured ceiling: `BUDGET_EXCEEDED`;
- unavailable executable, runner, filesystem, or required network service:
  `INFRA_FAILED`;
- ambiguous or unsafe recovery: `ESCALATED`.

Classification is based on typed failure reasons, not string matching against
tool output.

## Gate source resolution

Each hard gate uses a trusted, pinned gate specification defining its driver,
acceptance criteria, protected configuration, and permitted candidate inputs.

Candidate content is the subject of assessment and may include source code,
tests, and project configuration when explicitly declared by the gate
specification. Candidate-controlled files must not replace the trusted gate
driver, alter protected thresholds, remove required checks, or select which
evidence is considered authoritative.

A gate file created or modified inside the candidate workspace is inert unless
the trusted gate specification explicitly classifies that file as assessment
input. The trusted evaluator determines whether candidate changes to tests or
configuration weaken required coverage or policy.

## Usage accounting

The core directly enforces wall-clock and command-count budgets. Provider calls
must reserve a conservative token and cost allowance before execution whenever
the provider port exposes enforceable request limits.

Provider-reported actual usage and cost are advisory unless corroborated by a
trusted metering source. They may update accounting and prevent subsequent
calls, but cannot retroactively certify compliance with a budget on their own.

Phase 2A must exercise reservation, reconciliation, missing usage, delayed
usage, understated usage, and budget exhaustion through a deterministic fake
provider port. Captured-output size is an executor safety ceiling, not a
canonical contract budget unless a future schemas version defines it.

## Consequences

- Execution behavior is reproducible and auditable.
- Some tools requiring an interactive shell will be unsupported initially.
- Platform-specific isolation needs adapters and conformance tests.
- Output capture requires bounded storage and deterministic hashing.

## Rejected alternatives

### Run directly in the trusted checkout

Rejected because a failed or malicious builder could corrupt baseline or state.

### Accept arbitrary shell command strings

Rejected because quoting, expansion, and injection become policy bypasses.

### Rely only on agent instructions

Rejected because instructions are not an enforcement boundary.

## Acceptance conditions

- Tests prove the trusted checkout and evidence store are not builder-writable.
- Denied paths and actions fail before subprocess creation.
- Timeout terminates the process tree and produces a typed result.
- Environment and network defaults are deny-by-default.
- Captured outputs never enter telemetry attributes.
- Candidate gate files cannot replace or weaken the trusted gate harness.
- Budget tests remain deterministic when provider usage is missing, delayed,
  or understated.
