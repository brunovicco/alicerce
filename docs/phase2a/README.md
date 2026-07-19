# Phase 2A Readiness Pack

Status: Proposed
Review required: yes
Implementation authorized by this document: no

## Purpose

This pack converts the approved Phase 2 architecture into testable prerequisites
for the first trusted local-core implementation. It introduces no Python code,
dependencies, schemas, provider adapters, or remote side effects.

The upstream meaning of `NO_PROGRESS` was clarified by
`engineering-loop-schemas` PR #4, merge commit
`585e87447ba7007faf1a51a9f932164afd63d926`. Stall remains an internal signal;
the typed cause and authoritative evidence determine the canonical final state.

Executable contract provenance remains `engineering-loop-schemas v0.1.2` at
source commit `0459d61b7b1d4e7b46709e6d3895770553e6fab0`. The non-serialized
stall clarification is pinned separately to documentation decision
`585e87447ba7007faf1a51a9f932164afd63d926`. That documentation-only decision
does not require a schema release, tag, or consumer revendor.

## Documents

- [Package boundaries](package-boundaries.md)
- [Trusted gate specifications](trusted-gates.md)
- [Budget accounting](budget-accounting.md)
- [Artifact retention](artifact-retention.md)
- [Local human review](human-review.md)
- [Acceptance matrix](acceptance-matrix.md)
- [Authorization checklist](authorization-checklist.md)

## Scope of Phase 2A

Phase 2A may implement only a local, provider-neutral core with:

- immutable domain types and ports;
- pinned canonical schema integration;
- local state and artifact stores;
- isolated candidate workspaces;
- trusted command and gate execution;
- deterministic evidence and verdict construction;
- conservative budget accounting with a fake provider;
- no-op observability;
- local human-review requests.

Phase 2A may not implement provider SDKs, `a2a-otel-kit`, A2A, MCP protocol
adapters, GitHub mutations, merge, deploy, release, or remote multi-tenant
execution.

## Approval rule

The implementation authorization may change only in a review PR that:

1. marks every document in this pack Accepted;
2. resolves every row in the acceptance matrix;
3. confirms the schemas pin and upstream semantics;
4. updates the approved architecture proposal from
   `Implementation authorized: no` to an explicit Phase 2A-only authorization;
5. preserves all Phase 2B deferrals.
