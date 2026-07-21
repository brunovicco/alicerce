# Trusted Command Evidence Assembly

Status: Implemented
Decision date: 2026-07-21

## Scope

This increment maps one already validated operational ExecutionResult into the
canonical loop_schemas.models.CommandResult. It is a pure transformation: no
process is created, no filesystem is read, no artifact is persisted, and no
gate or verdict decision is made.

The mapper also receives the exact non-empty bytes of the immutable trusted
specification associated with the execution. It hashes those bytes directly;
it does not accept a caller-supplied specification digest.

## Command identity

The canonical schema currently represents command identity as a string.
Alicerce encodes the logical executable identifier and argv as a compact JSON
array with UTF-8 content:

~~~json
["python","-m","pytest","tests/unit test.py"]
~~~

This representation is shell-free and unambiguous. Spaces, quotes, variable
markers, and command separators remain inert argument content. The working
directory, environment authority, network policy, ceilings, and success rules
belong to the immutable trusted specification whose exact bytes are hashed into
the result.

## Field mapping

- operational EXITED, TIMED_OUT, CANCELLED, and OUTPUT_LIMIT map to the
  corresponding canonical uppercase termination values;
- the real exit code is preserved only for EXITED;
- duration is derived from the validated UTC execution interval with
  microsecond precision;
- stdout and stderr hashes cover the exact captured bytes without decoding or
  newline normalization;
- specification_sha256 covers the exact supplied specification bytes;
- the constructed value passes through canonical command-result serialization
  before it is returned.

## Trust boundary

The function assumes the ExecutionResult was returned by the trusted command
executor and that specification bytes were acquired from a trusted immutable
source. Empty or mistyped specification input fails closed.

This increment intentionally does not bind a candidate SHA because candidate
identity belongs to the complete top-level Evidence document, not an individual
canonical CommandResult.

## Acceptance impact

A08 gains executable mapping from bounded trusted execution into the canonical
command evidence shape. Tests prove exact output/specification binding,
shell-free argv identity, complete termination mapping, and deterministic
duration.

A08 remains partial until trusted code revalidates candidate identity, assembles
the full canonical Environment and Evidence values, and atomically persists
captured output plus evidence bytes.

## Explicit exclusions

- trusted gate specification construction or storage;
- gate success evaluation;
- candidate revalidation;
- complete Evidence assembly;
- output, evidence, verdict, or artifact persistence;
- runner, resume orchestration, providers, or observability;
- merge, deployment, release, hosting, or repository mutation.
