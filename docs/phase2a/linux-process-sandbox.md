# Linux process sandbox

## Scope

This increment implements the first real candidate-process backend for the
existing local command coordinator. It is Linux-specific, requires a pinned
bubblewrap executable, and supports only `NetworkPolicy.DENY_ALL`.

No `from __future__ import` directive is used.

## Enforcement sequence

For every execution the trusted adapter:

1. verifies the configured bubblewrap path, executable bit, and SHA-256;
2. probes the real deny-all namespace capability;
3. rejects the request if the probe fails or times out;
4. verifies bubblewrap again;
5. constructs argv without a shell or `PATH` lookup;
6. exposes `/usr` read-only and mounts only the candidate workspace writable;
7. binds the already pinned command executable at `/alicerce/executable`;
8. clears the environment and restores only explicit entries;
9. creates network, PID, IPC, and UTS namespaces;
10. captures stdout and stderr independently up to their configured ceilings;
11. terminates the sandbox process group on timeout or output exhaustion;
12. verifies bubblewrap after process cleanup;
13. returns a bounded `SandboxResult` to `LocalCommandExecutor`.

The coordinator continues to hold the workspace execution lease for this
entire sequence and validates workspace integrity after the backend returns.

## Tests

Deterministic adapter tests cover capability rejection, exact argument
construction, explicit environment, working-directory selection, normal and
nonzero exits, separate output ceilings, timeout, process-group termination,
spawn failure, capture failure, and changed bubblewrap identity.

A host-level test executes the real capability probe when bubblewrap exists.
The test records a Boolean result because some containerized CI environments
install bubblewrap while forbidding namespace creation. Such a host is correctly
unsupported and does not constitute evidence of successful confinement.

Full confinement evidence requires a CI profile where the real probe succeeds
and adversarial commands demonstrate network denial, write denial outside the
workspace, and process-tree cleanup. That profile is intentionally not claimed
by this increment.

## Acceptance impact

- A04 gains an OS-confinement implementation and exact writable-workspace
  mapping. It remains partial until the real conformance profile passes in CI.
- A06 gains fail-closed pre-spawn capability probing and shell-free execution.
  It remains partial because the executable bind still has a narrow
  verify-to-bind race that requires a stronger native handoff.
- A07 gains enforced timeout, output ceilings, and process-group termination.
  It remains partial until adversarial real-backend tests prove descendant
  cleanup on the supported CI profile.
- A08 remains open until trusted code hashes and persists captured outputs,
  candidate identity, environment identity, and gate specification identity.

## Explicit exclusions

- macOS or Windows process backends;
- a direct subprocess fallback;
- orchestrator cancellation;
- gates, evidence, verdicts, or artifact persistence;
- observability and provider integrations;
- merge, deployment, release, or GitHub mutation capabilities.
