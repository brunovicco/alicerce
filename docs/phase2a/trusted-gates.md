# Phase 2A Trusted Gate Specifications

Status: Proposed

## Principle

Candidate content is assessed by a trusted gate harness. A candidate may be an
input to a gate but cannot select the gate driver, remove required checks,
change protected thresholds, or choose authoritative evidence.

## Gate specification

Each gate specification is immutable for a run and bound into run state by a
stable hash. It defines:

- canonical gate name;
- trusted driver identity and argv template;
- protected configuration and thresholds;
- explicitly permitted candidate inputs;
- working-directory policy;
- environment allowlist;
- network policy;
- timeout and termination grace period;
- output ceilings;
- success exit codes;
- evidence fields to collect.

Specifications resolve from installed trusted policy, the pinned contract, or a
trusted baseline path outside the candidate workspace.

## Candidate inputs

Source, tests, and project configuration may be candidate inputs only when the
specification declares them. Candidate configuration is never implicitly
trusted. A change to tests or configuration is assessed as content and cannot
replace protected acceptance policy.

A candidate-created gate script is inert unless explicitly classified as an
input. Even then, it cannot become the trusted driver for its own run.

## Initial gate names

The runner recognizes only the contract-addressable vocabulary already
documented by schemas:

`lock`, `lint`, `format`, `typing`, `tests`, `security`,
`dependencies`, `architecture`, `mcp`, and `governance`.

Phase 2A may implement a representative local subset, but unknown or unavailable
required gates fail closed. No required gate may be silently skipped.

This candidate-gate vocabulary and Alicerce's repository quality gate are
separate policy scopes. Shared names do not imply shared drivers,
configuration, thresholds, or lifecycle. Each list evolves only through its
own trusted policy and review process.

## Tamper tests

Tests must demonstrate that a candidate cannot obtain success by:

- replacing a gate driver;
- editing a protected threshold;
- deleting a required gate;
- changing trusted environment or network policy;
- shadowing trusted Python modules;
- forging a gate result or evidence hash;
- editing state between gate execution and verdict construction.

## Acceptance criteria

- Every executed gate specification hash is persisted with run state.
- Gate results identify both the candidate SHA and trusted specification hash.
- Required unknown or unavailable gates produce a typed fail-closed outcome.
- Candidate gate tampering is inert and covered by regression tests.
- Builder self-reports never satisfy a gate.
