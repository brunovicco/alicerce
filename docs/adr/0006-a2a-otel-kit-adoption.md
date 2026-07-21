# ADR 0006: Linux process sandbox

Status: Accepted
Date: 2026-07-20

## Context

The provider-neutral command boundary and local coordinator deliberately stop
before process creation. Phase 2A now needs its first candidate-process adapter
without weakening `NetworkPolicy.DENY_ALL`, inheriting host authority, or
presenting a portable interface as portable enforcement.

Python subprocess controls alone cannot provide filesystem and network
confinement. Linux and macOS expose different primitives, and their failure
modes must remain visible.

## Decision

Implement a Linux-only `LinuxProcessSandboxBackend` using an explicitly
configured and content-pinned `bubblewrap` executable.

Before accepting a deny-all request, the adapter executes a minimal capability
probe using the same namespace and mount controls required by candidate
commands. A failed or timed-out probe means the policy is unsupported and the
candidate executable is not spawned.

The sandbox:

- creates network, PID, IPC, and UTS namespaces;
- uses a new session and dies with its parent;
- exposes `/usr` read-only for the runtime and constructs compatibility links;
- mounts only the exact candidate workspace as writable;
- binds the pinned candidate executable at a fixed sandbox path;
- clears the sandbox environment and sets only explicit entries;
- changes to the validated working directory without a shell;
- captures stdout and stderr independently with hard byte ceilings;
- applies timeout and termination grace limits;
- terminates the complete host-side sandbox process group;
- verifies the bubblewrap binary before the probe, before spawn, and after
  completion.

The adapter is reexported as a local composition component. Its underlying
`ProcessSandboxBackend` protocol remains adapter-private.

## Consequences

Linux deployments require bubblewrap and kernel/runtime permission to create
the namespaces. Installation alone is insufficient; the capability probe is
authoritative.

Hosts that disable user namespaces or otherwise block bubblewrap fail closed.
There is no direct-process fallback and no macOS emulation.

The system runtime is readable through `/usr`; arbitrary host roots, home
directories, the trusted checkout, state, and evidence roots are not mounted.
The coordinator's workspace lease and post-execution checks remain mandatory.

## Deferred work

- macOS-specific isolation;
- trusted CI provisioning that exercises the real confinement profile;
- cancellation initiated by the orchestrator;
- durable output and evidence hashing;
- cross-process execution leases and crash recovery.

## Rejected alternatives

### Plain subprocess with resource limits

Rejected because it cannot enforce the required network or filesystem policy.

### Read-only bind of the complete host root

Rejected because it would expose secrets and unrelated trusted state to the
candidate even when writes were denied.

### Silent fallback when bubblewrap is unavailable

Rejected because an unavailable enforcement mechanism is an infrastructure
failure, not permission to run with weaker isolation.

## Linux conformance profile

The supported CI profile runs on Ubuntu 24.04 with an explicitly installed
bubblewrap package and Python 3.12. The runner configuration enables
unprivileged user namespaces when Ubuntu AppArmor restricts them. The candidate
still runs as the unprivileged runner user; bubblewrap is never invoked through
sudo.

The profile fails before adversarial execution if the production capability
probe cannot create the required namespaces. Missing bubblewrap, a symlinked
binary, rejected namespaces, or a failed probe is an infrastructure failure and
cannot become a skipped or weakened execution.

Adversarial tests prove that the sandbox cannot reach a listener in the host
network namespace, cannot write outside the mounted workspace, receives only
explicit environment entries, returns a typed timeout, and terminates
descendants that resist SIGTERM.
