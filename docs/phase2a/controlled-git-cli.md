# Controlled Git CLI Boundary

Status: Implemented
Decision date: 2026-07-20

## Decision

The first Phase 2A filesystem and process primitive uses a controlled Git CLI
against a trusted local source repository. It creates a standalone disposable
clone rather than a linked worktree or a filesystem copy.

`ControlledGitCli` is deliberately internal to the local adapter package. Its
only public operation materializes one exact `BaselineSha`; callers cannot
supply arbitrary Git arguments or execute unrelated commands through it.

## Process policy

The executable must be supplied as an absolute path resolving to an executable
regular file. The implementation never searches `PATH`, invokes a shell, or
inherits caller-controlled Git environment variables.

Every invocation uses:

- structured argument vectors and `shell=False`;
- closed standard input;
- a fixed positive timeout;
- captured stdout and stderr with a configured acceptance limit;
- an isolated `HOME` and `XDG_CONFIG_HOME`;
- disabled system configuration, terminal prompts, askpass, and hooks;
- `GIT_ALLOW_PROTOCOL=file` because only a validated local source is accepted;
- deterministic UTF-8 locale and strict stdout decoding.

Failures expose stable causes without embedding stdout, stderr, repository
paths, or process environment values in the exception message.

## Filesystem policy

Source and destination must be `Path` values and absolute. The source is
resolved strictly and must be a directory. The destination parent is resolved
strictly, while the destination itself must not exist, be a symlink, or be
nested within the source repository.

Materialization uses `git clone --no-local --no-hardlinks --no-checkout` to
avoid linked object storage and local hardlink optimization. It then checks out
the complete baseline in detached mode, verifies `HEAD^{commit}` byte-for-byte
against the requested SHA, and removes `origin`. A failed operation removes
only the newly validated destination and returns no result.

The immutable `MaterializedBaseline` result contains only the absolute local
repository path and verified semantic `BaselineSha`. It is adapter-local and
is not exposed through a provider-neutral port.

## Acceptance impact

A04 gains executable integration evidence for independent baseline
materialization and a controlled process environment. It remains partial:
capability-owned root mapping, protected-root checks, symlink scanning, release
policy, and confinement of future candidate commands are not yet implemented.

A08 gains verification that the prepared checkout starts at the exact baseline
commit. It remains open until trusted candidate snapshot and evidence bindings
are implemented.

A19 remains protected. This primitive exposes no branch, push, merge, hosting,
deployment, or release operation and removes the clone remote before returning.

## Explicit exclusions

This increment does not implement:

- `WorkspacePort` or capability-to-path mapping;
- candidate snapshot or `CandidateSha` computation;
- generic command execution or `CommandExecutorPort`;
- process sandboxing for untrusted candidate commands;
- workspace loading, persistence, resume, or release;
- network cloning, fetch, pull, push, branches, merge, deployment, or release;
- submodule initialization or Git LFS;
- artifact, evidence, provider, or observability behavior.
