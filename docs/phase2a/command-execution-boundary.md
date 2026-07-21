# Controlled Command Execution Boundary

Status: Implemented
Decision date: 2026-07-20

## Scope

This increment defines the provider-neutral values and port required for future
controlled command execution. It creates no process, resolves no executable,
opens no filesystem path, and performs no network operation.

`CommandRequest` binds the complete `RunIdentity` to an immutable
`WorkspaceIdentity` capability instead of a host path. It carries a logical executable identifier, semantic action,
argv arguments, normalized workspace-relative directory, explicit environment,
deny-all network policy, and positive execution and output ceilings.

Logical executable identifiers are not filenames. A future trusted local
adapter must map each identifier to an administrator-configured executable and
reject unknown identifiers before process creation. Arguments are represented
as a tuple and never as a shell command string.

## Determinism and validation

Environment entries must be unique and sorted by name. Working directories use
normalized relative POSIX notation and cannot contain absolute roots, parent
traversal, platform separators, or NUL. Arguments and environment values also
reject NUL rather than normalizing candidate input.

`CommandLimits` carries integer millisecond timeout and termination-grace
ceilings plus independent stdout and stderr byte ceilings. Boolean and floating
point coercion are rejected.

`ExecutionResult` is an immutable operational value bound to the complete
request. Normal exit requires an integer exit code; timeout, cancellation, and
output-ceiling termination require no exit code. Captured byte strings cannot
exceed the request ceilings, and timestamps must be ordered UTC values.

An operational result is not authoritative evidence and does not decide whether
a gate passed. The later evidence collector will map validated execution data
into the canonical `loop_schemas.models.CommandResult`; Alicerce does not define
a competing serialized command-result model. The pinned v0.2.0 model provides
typed termination, nullable exit codes, both output hashes, and the trusted gate
specification hash. Availability of that shape is not evidence collection.

## Port contract

`CommandExecutorPort.execute` accepts one prevalidated `AuthorizedCommand` and
either returns an `ExecutionResult` or raises `CommandExecutionError` with a
stable typed cause. Raw requests first pass through the trusted pre-spawn
authorization use case.
A nonzero exit code remains a result. Policy denial, missing workspace,
unavailable executable, spawn failure, failed cleanup, and isolation failure are
port errors and are never inferred by matching stdout or stderr text.

The protocol is structural and is not runtime-checkable. This increment ships
no implementation or production fake; the reference double exists only in
tests.

## Acceptance impact

A06 gains immutable request values and typed pre-spawn denial semantics. It
remains partial until a trusted adapter proves that denied actions, paths,
environment entries, executables, and network requests fail before spawn.

A07 remains open until the local adapter enforces timeout, termination grace,
process-tree cleanup, cancellation, and output ceilings against real processes.

A08 gains deterministic operational inputs and bounded outputs, but remains
open until trusted code binds their hashes, the candidate SHA, environment, and
specification identity into canonical evidence.

A04 remains partial until actual candidate processes receive OS-level
confinement. A19 remains protected because the port exposes no Git promotion,
merge, deployment, release, hosting, or branch-protection authority.

## Explicit exclusions

This increment does not implement:

- subprocess creation, shells, executable discovery, or process-tree cleanup;
- local workspace-path resolution;
- OS sandboxing, filesystem confinement, or network enforcement;
- trusted gate specifications or gate execution;
- output hashing, evidence, verdict, artifacts, or telemetry;
- budgets, providers, resume orchestration, or human review;
- merge, deployment, release, hosting, or GitHub mutations.
