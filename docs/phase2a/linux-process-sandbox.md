# Linux process sandbox

## Scope

This increment implements and verifies the first real candidate-process backend
for the existing local command coordinator. It is Linux-specific, requires a
pinned bubblewrap executable, and supports only `NetworkPolicy.DENY_ALL`.

No `from __future__ import` directive is used.

## Enforcement sequence

For every execution the trusted adapter:

1. verifies the configured bubblewrap path, executable bit, and SHA-256;
2. probes the real deny-all namespace capability;
3. rejects the request if the probe fails or times out;
4. verifies bubblewrap again;
5. constructs argv without a shell or `PATH` lookup;
6. exposes `/usr` read-only;
7. binds the pinned command executable at `/alicerce/executable`;
8. makes the private `/alicerce` directory non-writable;
9. mounts the exact candidate workspace at `/workspace`;
10. creates no general-purpose writable `/tmp`;
11. clears the inherited environment, restores explicit entries, and accepts only
the deterministic sandbox PWD added by bubblewrap;
12. creates network, PID, IPC, and UTS namespaces;
13. captures stdout and stderr independently up to their configured ceilings;
14. terminates the sandbox process group on timeout or output exhaustion;
15. verifies bubblewrap after process cleanup;
16. returns a bounded `SandboxResult` to `LocalCommandExecutor`.

The coordinator continues to hold the workspace execution lease for this
entire sequence and validates workspace integrity after the backend returns.

## Portable unit tests

Deterministic tests use a fake bubblewrap executable and run on Linux and macOS.
They cover capability rejection, exact argument construction, fixed workspace
mapping, explicit environment, working-directory selection, normal and nonzero
exits, separate output ceilings, timeout, process-group termination, spawn
failure, capture failure, and changed bubblewrap identity.

The optional host capability test remains non-authoritative because a developer
machine can have bubblewrap installed while its kernel or container runtime
rejects namespace creation.

## Required Linux conformance profile

`tests/test_linux_process_sandbox_conformance.py` is inactive during the
portable suite. The dedicated CI job activates it with:

```text
ALICERCE_LINUX_SANDBOX_CONFORMANCE=1
```

Once activated, Linux, a real non-symlink bubblewrap executable, and successful
namespace creation are mandatory. The profile contains no mocks or fake process
backend and fails rather than skips when the configured host cannot provide the
required isolation.

The adversarial cases prove:

- the sandbox cannot reach a TCP listener in the host network namespace;
- the candidate can write inside `/workspace`;
- system, private adapter, temporary, and arbitrary host paths are not writable;
- no host environment entries reach the candidate; only declared entries and the
deterministic `/workspace` PWD are present;
- timeout produces `ExecutionTermination.TIMED_OUT`;
- descendants that ignore SIGTERM stop updating workspace state and cannot
  perform a delayed write after the backend returns.

The GitHub Actions job is separate from the Python compatibility matrix. It runs
on Ubuntu 24.04 and Python 3.12, installs bubblewrap explicitly, records its
version, configures unprivileged namespaces when required by AppArmor, performs
a required capability preflight, and only then runs the remaining tests.

## Fail-closed conditions

The conformance job fails if:

- bubblewrap is missing, symlinked, non-executable, or changes identity;
- namespace configuration is unavailable;
- the production capability probe returns false;
- network or filesystem confinement is weaker than declared;
- the candidate receives an inherited environment entry;
- timeout does not return the typed result;
- a resistant descendant remains active after cleanup.

There is no direct-process fallback and no conversion of these failures into a
skip.

## Acceptance impact

- A04 is demonstrated for the supported Linux profile by adversarial
  workspace-only persistent-write tests. Cross-platform confinement is not
  claimed.
- A06 is demonstrated for this profile by mandatory namespace probing, real
  network denial, shell-free execution, and explicit environment checks. The
  narrow executable verify-to-bind race remains documented.
- A07 is demonstrated for this profile by real timeout and resistant-descendant
  cleanup tests.
- A08 remains open until trusted code hashes and persists captured outputs,
  candidate identity, environment identity, and gate specification identity.

## Explicit exclusions

- macOS or Windows process backends;
- a direct subprocess fallback;
- orchestrator cancellation;
- gates, evidence, verdicts, or artifact persistence;
- observability and provider integrations;
- merge, deployment, release, or GitHub mutation capabilities.
