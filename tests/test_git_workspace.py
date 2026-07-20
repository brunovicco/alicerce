"""Integration tests for the capability-owned local Git workspace adapter."""

import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Thread

import pytest

from alicerce.adapters.local import git_workspace as workspace_module
from alicerce.adapters.local.git_cli import (
    ControlledGitCli,
    GitCliError,
    GitCliErrorCause,
    MaterializedBaseline,
)
from alicerce.adapters.local.git_workspace import LocalGitWorkspace
from alicerce.domain.run_identity import (
    BaselineSha,
    ContractHash,
    ContractId,
    ContractVersion,
    PolicyHash,
    RunId,
    RunIdentity,
)
from alicerce.domain.workspace import CandidateSha, WorkspaceId, WorkspaceIdentity
from alicerce.ports.workspace import WorkspaceError, WorkspaceErrorCause, WorkspacePort

NOW = datetime(2026, 7, 20, 2, 0, tzinfo=UTC)


class SequenceWorkspaceIds:
    """Deterministic test-only capability generator."""

    def __init__(self, *values: str) -> None:
        self._values = iter(values)

    def new_workspace_id(self) -> WorkspaceId:
        return WorkspaceId(next(self._values))


class FailingGit(ControlledGitCli):
    """Controlled primitive double that fails one selected operation."""

    def __init__(self, executable: Path, operation: str, cause: GitCliErrorCause) -> None:
        super().__init__(executable)
        self._operation = operation
        self._cause = cause
        self._verify_calls = 0

    def materialize_baseline(
        self, source: Path, destination: Path, baseline_sha: BaselineSha
    ) -> MaterializedBaseline:
        if self._operation == "materialize":
            raise GitCliError(self._cause, "injected")
        return super().materialize_baseline(source, destination, baseline_sha)

    def verify_baseline(self, repository: Path, baseline_sha: BaselineSha) -> MaterializedBaseline:
        self._verify_calls += 1
        if self._operation == "verify":
            raise GitCliError(self._cause, "injected")
        if self._operation == "verify_after_prepare" and self._verify_calls > 1:
            raise GitCliError(self._cause, "injected")
        return super().verify_baseline(repository, baseline_sha)

    def snapshot_candidate(self, repository: Path) -> CandidateSha:
        if self._operation == "snapshot":
            raise GitCliError(self._cause, "injected")
        return super().snapshot_candidate(repository)


class OSErrorGit(ControlledGitCli):
    """Test double for an adapter-local filesystem failure."""

    def materialize_baseline(
        self, source: Path, destination: Path, baseline_sha: BaselineSha
    ) -> MaterializedBaseline:
        raise OSError("injected")


class FileReplacingGit(ControlledGitCli):
    """Test double that leaves a non-directory partial destination."""

    def materialize_baseline(
        self, source: Path, destination: Path, baseline_sha: BaselineSha
    ) -> MaterializedBaseline:
        destination.write_text("partial", encoding="utf-8")
        raise GitCliError(GitCliErrorCause.COMMAND_FAILED, "injected")


def _git() -> Path:
    executable = shutil.which("git")
    assert executable is not None
    return Path(executable).resolve()


def _run_git(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(  # noqa: S603
        (str(_git()), "-C", str(repository), *arguments),
        check=True,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        env={"HOME": str(repository.parent), "LC_ALL": "C.UTF-8"},
    )
    return completed.stdout.decode().strip()


def _source_repository(tmp_path: Path) -> tuple[Path, BaselineSha]:
    source = tmp_path / "source"
    source.mkdir()
    _run_git(source, "init", "--initial-branch=main")
    _run_git(source, "config", "user.name", "Alicerce Tests")
    _run_git(source, "config", "user.email", "tests@alicerce.invalid")
    (source / "payload.txt").write_text("baseline\n", encoding="utf-8")
    _run_git(source, "add", "payload.txt")
    _run_git(source, "commit", "-m", "baseline")
    return source, BaselineSha(_run_git(source, "rev-parse", "HEAD"))


def _identity(baseline: BaselineSha, run_id: str = "run-workspace") -> RunIdentity:
    return RunIdentity(
        run_id=RunId(run_id),
        contract_id=ContractId("quality-loop"),
        contract_version=ContractVersion("0.1.2"),
        contract_hash=ContractHash("a" * 64),
        baseline_sha=baseline,
        policy_hash=PolicyHash("b" * 64),
        created_at=NOW,
    )


def _adapter(
    tmp_path: Path,
    source: Path,
    *ids: str,
    git: ControlledGitCli | None = None,
) -> tuple[LocalGitWorkspace, Path, Path]:
    root = tmp_path / "workspaces"
    protected = tmp_path / "protected"
    root.mkdir(exist_ok=True)
    protected.mkdir(exist_ok=True)
    adapter = LocalGitWorkspace(
        source_repository=source,
        workspace_root=root,
        protected_roots=(protected,),
        git=git or ControlledGitCli(_git()),
        id_generator=SequenceWorkspaceIds(*ids),
    )
    return adapter, root, protected


def test_adapter_satisfies_port_and_materializes_exact_private_path(tmp_path: Path) -> None:
    source, baseline = _source_repository(tmp_path)
    adapter, root, _ = _adapter(tmp_path, source, "workspace-001")
    port: WorkspacePort = adapter
    workspace = port.prepare(_identity(baseline))

    assert workspace == WorkspaceIdentity(
        WorkspaceId("workspace-001"), RunId("run-workspace"), baseline
    )
    assert port.load(workspace.workspace_id) == workspace
    checkout = root / workspace.workspace_id.value
    assert _run_git(checkout, "rev-parse", "HEAD") == baseline.value
    assert _run_git(checkout, "remote") == ""
    assert set(workspace.__dataclass_fields__) == {
        "workspace_id",
        "run_id",
        "baseline_sha",
    }


def test_prepare_rejects_duplicate_run_and_capability(tmp_path: Path) -> None:
    source, baseline = _source_repository(tmp_path)
    adapter, _, _ = _adapter(tmp_path, source, "same", "same")
    adapter.prepare(_identity(baseline))
    with pytest.raises(WorkspaceError) as duplicate_run:
        adapter.prepare(_identity(baseline))
    assert duplicate_run.value.cause is WorkspaceErrorCause.ALREADY_EXISTS
    with pytest.raises(WorkspaceError) as duplicate_id:
        adapter.prepare(_identity(baseline, "another-run"))
    assert duplicate_id.value.cause is WorkspaceErrorCause.ALREADY_EXISTS


def test_snapshot_binds_deterministic_tree_without_mutating_real_index(tmp_path: Path) -> None:
    source, baseline = _source_repository(tmp_path)
    adapter, root, _ = _adapter(tmp_path, source, "workspace")
    workspace = adapter.prepare(_identity(baseline))
    checkout = root / "workspace"
    original_index = _run_git(checkout, "write-tree")
    (checkout / "payload.txt").write_text("changed\n", encoding="utf-8")
    (checkout / "new.txt").write_text("new\n", encoding="utf-8")

    first = adapter.snapshot(workspace)
    second = adapter.snapshot(workspace)

    assert first == second
    assert first.workspace is workspace
    assert first.candidate_sha.value != _run_git(checkout, "rev-parse", "HEAD^{tree}")
    assert _run_git(checkout, "write-tree") == original_index


def test_external_symlink_is_rejected_during_prepare_and_removed(tmp_path: Path) -> None:
    source, baseline = _source_repository(tmp_path)
    protected_target = tmp_path / "outside.txt"
    protected_target.write_text("protected\n", encoding="utf-8")
    (source / "escape").symlink_to(protected_target)
    _run_git(source, "add", "escape")
    _run_git(source, "commit", "-m", "escaping symlink")
    baseline = BaselineSha(_run_git(source, "rev-parse", "HEAD"))
    adapter, root, _ = _adapter(tmp_path, source, "workspace")

    with pytest.raises(WorkspaceError) as captured:
        adapter.prepare(_identity(baseline))

    assert captured.value.cause is WorkspaceErrorCause.ISOLATION_FAILURE
    assert not (root / "workspace").exists()
    assert protected_target.read_text(encoding="utf-8") == "protected\n"
    assert adapter.load(WorkspaceId("workspace")) is None


def test_load_and_snapshot_detect_integrity_changes(tmp_path: Path) -> None:
    source, baseline = _source_repository(tmp_path)
    adapter, root, _ = _adapter(tmp_path, source, "workspace")
    workspace = adapter.prepare(_identity(baseline))
    checkout = root / "workspace"
    config = checkout / ".git" / "config"
    original = config.read_bytes()
    config.write_bytes(original + b'\n[filter "evil"]\n\tclean = false\n')

    with pytest.raises(WorkspaceError) as load_error:
        adapter.load(workspace.workspace_id)
    assert load_error.value.cause is WorkspaceErrorCause.ISOLATION_FAILURE
    with pytest.raises(WorkspaceError) as snapshot_error:
        adapter.snapshot(workspace)
    assert snapshot_error.value.cause is WorkspaceErrorCause.ISOLATION_FAILURE


def test_snapshot_rejects_symlink_added_after_prepare(tmp_path: Path) -> None:
    source, baseline = _source_repository(tmp_path)
    adapter, root, protected = _adapter(tmp_path, source, "workspace")
    workspace = adapter.prepare(_identity(baseline))
    (root / "workspace" / "escape").symlink_to(protected)

    with pytest.raises(WorkspaceError) as captured:
        adapter.snapshot(workspace)
    assert captured.value.cause is WorkspaceErrorCause.ISOLATION_FAILURE


def test_release_is_idempotent_and_allows_new_capability_for_run(tmp_path: Path) -> None:
    source, baseline = _source_repository(tmp_path)
    adapter, root, _ = _adapter(tmp_path, source, "first", "second")
    identity = _identity(baseline)
    first = adapter.prepare(identity)
    adapter.release(first)
    adapter.release(first)
    assert not (root / "first").exists()
    assert adapter.load(first.workspace_id) is None
    second = adapter.prepare(identity)
    assert second.workspace_id == WorkspaceId("second")


def test_release_rejects_stale_identity_without_removing_workspace(tmp_path: Path) -> None:
    source, baseline = _source_repository(tmp_path)
    adapter, root, _ = _adapter(tmp_path, source, "workspace")
    workspace = adapter.prepare(_identity(baseline))
    stale = WorkspaceIdentity(workspace.workspace_id, RunId("other-run"), baseline)
    with pytest.raises(WorkspaceError) as captured:
        adapter.release(stale)
    assert captured.value.cause is WorkspaceErrorCause.CONFLICT
    assert (root / "workspace").is_dir()


def test_release_unlinks_symlink_attack_without_touching_protected_root(tmp_path: Path) -> None:
    source, baseline = _source_repository(tmp_path)
    adapter, root, protected = _adapter(tmp_path, source, "workspace")
    workspace = adapter.prepare(_identity(baseline))
    shutil.rmtree(root / "workspace")
    (root / "workspace").symlink_to(protected, target_is_directory=True)

    with pytest.raises(WorkspaceError) as captured:
        adapter.release(workspace)

    assert captured.value.cause is WorkspaceErrorCause.ISOLATION_FAILURE
    assert protected.is_dir()
    assert not (root / "workspace").exists()
    adapter.release(workspace)


def test_missing_workspace_release_forgets_record_safely(tmp_path: Path) -> None:
    source, baseline = _source_repository(tmp_path)
    adapter, root, _ = _adapter(tmp_path, source, "workspace", "replacement")
    identity = _identity(baseline)
    workspace = adapter.prepare(identity)
    shutil.rmtree(root / "workspace")
    adapter.release(workspace)
    assert adapter.prepare(identity).workspace_id == WorkspaceId("replacement")


def test_release_recovers_detached_quarantine_from_prior_failure(tmp_path: Path) -> None:
    source, baseline = _source_repository(tmp_path)
    adapter, root, _ = _adapter(tmp_path, source, "workspace", "replacement")
    identity = _identity(baseline)
    workspace = adapter.prepare(identity)
    (root / "workspace").rename(root / ".release-workspace")

    adapter.release(workspace)

    assert not (root / ".release-workspace").exists()
    assert adapter.prepare(identity).workspace_id == WorkspaceId("replacement")


def test_release_recovers_non_directory_quarantine(tmp_path: Path) -> None:
    source, baseline = _source_repository(tmp_path)
    adapter, root, _ = _adapter(tmp_path, source, "workspace")
    workspace = adapter.prepare(_identity(baseline))
    shutil.rmtree(root / "workspace")
    (root / ".release-workspace").write_text("detached", encoding="utf-8")
    adapter.release(workspace)
    assert not (root / ".release-workspace").exists()


def test_release_reports_quarantine_recovery_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, baseline = _source_repository(tmp_path)
    adapter, root, _ = _adapter(tmp_path, source, "workspace")
    workspace = adapter.prepare(_identity(baseline))
    (root / "workspace").rename(root / ".release-workspace")

    def fail_remove(path: Path) -> None:
        raise OSError(path)

    monkeypatch.setattr(workspace_module.shutil, "rmtree", fail_remove)
    with pytest.raises(WorkspaceError) as captured:
        adapter.release(workspace)
    assert captured.value.cause is WorkspaceErrorCause.STORAGE_FAILURE


@pytest.mark.parametrize(
    ("operation", "git_cause", "workspace_cause"),
    [
        ("materialize", GitCliErrorCause.BASELINE_MISMATCH, WorkspaceErrorCause.ISOLATION_FAILURE),
        ("materialize", GitCliErrorCause.TIMEOUT, WorkspaceErrorCause.STORAGE_FAILURE),
        ("verify", GitCliErrorCause.INVALID_PATH, WorkspaceErrorCause.ISOLATION_FAILURE),
    ],
)
def test_git_failures_are_translated_without_leaking_details(
    tmp_path: Path,
    operation: str,
    git_cause: GitCliErrorCause,
    workspace_cause: WorkspaceErrorCause,
) -> None:
    source, baseline = _source_repository(tmp_path)
    failing = FailingGit(_git(), operation, git_cause)
    adapter, _, _ = _adapter(tmp_path, source, "workspace", git=failing)
    with pytest.raises(WorkspaceError) as captured:
        adapter.prepare(_identity(baseline))
    assert captured.value.cause is workspace_cause
    assert "injected" not in str(captured.value)


def test_constructor_rejects_unsafe_or_overlapping_roots(tmp_path: Path) -> None:
    source, _ = _source_repository(tmp_path)
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(ValueError, match="disjoint"):
        LocalGitWorkspace(
            source_repository=source,
            workspace_root=source / ".git",
            protected_roots=(root,),
            git=ControlledGitCli(_git()),
            id_generator=SequenceWorkspaceIds("workspace"),
        )
    with pytest.raises(ValueError, match="absolute"):
        LocalGitWorkspace(
            source_repository=source,
            workspace_root=Path("relative"),
            protected_roots=(root,),
            git=ControlledGitCli(_git()),
            id_generator=SequenceWorkspaceIds("workspace"),
        )


def test_public_operations_reject_semantic_type_confusion(tmp_path: Path) -> None:
    source, baseline = _source_repository(tmp_path)
    adapter, _, _ = _adapter(tmp_path, source, "workspace")
    with pytest.raises(TypeError):
        adapter.prepare(object())  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        adapter.load("workspace")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        adapter.snapshot(object())  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        adapter.release(object())  # type: ignore[arg-type]
    assert baseline.value


def test_constructor_rejects_wrong_configuration_types_and_missing_paths(tmp_path: Path) -> None:
    source, _ = _source_repository(tmp_path)
    root = tmp_path / "root"
    root.mkdir()
    source_file = tmp_path / "source-file"
    source_file.write_text("file", encoding="utf-8")
    common: dict[str, object] = {
        "source_repository": source,
        "workspace_root": root,
        "protected_roots": (),
        "git": ControlledGitCli(_git()),
        "id_generator": SequenceWorkspaceIds("workspace"),
    }
    for key, value, error in (
        ("source_repository", "source", TypeError),
        ("protected_roots", [], TypeError),
        ("git", object(), TypeError),
        ("id_generator", object(), TypeError),
        ("source_repository", tmp_path / "missing", ValueError),
        ("source_repository", source_file, ValueError),
    ):
        arguments = dict(common)
        arguments[key] = value
        with pytest.raises(error):
            LocalGitWorkspace(**arguments)  # type: ignore[arg-type]


def test_generator_must_return_semantic_workspace_id(tmp_path: Path) -> None:
    source, baseline = _source_repository(tmp_path)

    class WrongGenerator:
        def new_workspace_id(self) -> object:
            return "workspace"

    root = tmp_path / "root"
    root.mkdir()
    adapter = LocalGitWorkspace(
        source_repository=source,
        workspace_root=root,
        protected_roots=(),
        git=ControlledGitCli(_git()),
        id_generator=WrongGenerator(),  # type: ignore[arg-type]
    )
    with pytest.raises(TypeError):
        adapter.prepare(_identity(baseline))


def test_prepare_translates_local_oserror_and_removes_partial_file(tmp_path: Path) -> None:
    source, baseline = _source_repository(tmp_path)
    failing = OSErrorGit(_git())
    adapter, _, _ = _adapter(tmp_path, source, "workspace", git=failing)
    with pytest.raises(WorkspaceError) as os_error:
        adapter.prepare(_identity(baseline))
    assert os_error.value.cause is WorkspaceErrorCause.STORAGE_FAILURE

    partial = FileReplacingGit(_git())
    adapter, root, _ = _adapter(tmp_path, source, "partial", git=partial)
    with pytest.raises(WorkspaceError):
        adapter.prepare(_identity(baseline, "partial-run"))
    assert not (root / "partial").exists()


@pytest.mark.parametrize(
    ("operation", "expected"),
    [
        ("snapshot", WorkspaceErrorCause.STORAGE_FAILURE),
        ("verify_after_prepare", WorkspaceErrorCause.ISOLATION_FAILURE),
    ],
)
def test_existing_workspace_git_failures_are_translated(
    tmp_path: Path, operation: str, expected: WorkspaceErrorCause
) -> None:
    source, baseline = _source_repository(tmp_path)
    failing = FailingGit(_git(), operation, GitCliErrorCause.BASELINE_MISMATCH)
    if operation == "snapshot":
        failing = FailingGit(_git(), operation, GitCliErrorCause.COMMAND_FAILED)
    adapter, _, _ = _adapter(tmp_path, source, "workspace", git=failing)
    workspace = adapter.prepare(_identity(baseline))
    with pytest.raises(WorkspaceError) as captured:
        if operation == "snapshot":
            adapter.snapshot(workspace)
        else:
            adapter.load(workspace.workspace_id)
    assert captured.value.cause is expected


def test_snapshot_rejects_missing_and_stale_capabilities(tmp_path: Path) -> None:
    source, baseline = _source_repository(tmp_path)
    adapter, _, _ = _adapter(tmp_path, source, "workspace")
    workspace = adapter.prepare(_identity(baseline))
    missing = WorkspaceIdentity(WorkspaceId("missing"), workspace.run_id, baseline)
    stale = WorkspaceIdentity(workspace.workspace_id, RunId("other-run"), baseline)
    with pytest.raises(WorkspaceError) as absent:
        adapter.snapshot(missing)
    assert absent.value.cause is WorkspaceErrorCause.NOT_FOUND
    with pytest.raises(WorkspaceError) as conflict:
        adapter.snapshot(stale)
    assert conflict.value.cause is WorkspaceErrorCause.CONFLICT


def test_root_replacement_is_detected_before_prepare(tmp_path: Path) -> None:
    source, baseline = _source_repository(tmp_path)
    adapter, root, protected = _adapter(tmp_path, source, "workspace")
    root.rmdir()
    with pytest.raises(WorkspaceError) as missing:
        adapter.prepare(_identity(baseline))
    assert missing.value.cause is WorkspaceErrorCause.STORAGE_FAILURE

    root.symlink_to(protected, target_is_directory=True)
    with pytest.raises(WorkspaceError) as replaced:
        adapter.prepare(_identity(baseline))
    assert replaced.value.cause is WorkspaceErrorCause.ISOLATION_FAILURE
    root.unlink()


def test_load_rejects_replaced_directory_and_missing_git_config(tmp_path: Path) -> None:
    source, baseline = _source_repository(tmp_path)
    adapter, root, _ = _adapter(tmp_path, source, "workspace")
    workspace = adapter.prepare(_identity(baseline))
    shutil.rmtree(root / "workspace")
    (root / "workspace").write_text("replacement", encoding="utf-8")
    with pytest.raises(WorkspaceError) as replaced:
        adapter.load(workspace.workspace_id)
    assert replaced.value.cause is WorkspaceErrorCause.ISOLATION_FAILURE

    (root / "workspace").unlink()
    adapter, root, _ = _adapter(tmp_path, source, "config")
    workspace = adapter.prepare(_identity(baseline, "config-run"))
    (root / "config" / ".git" / "config").unlink()
    with pytest.raises(WorkspaceError) as missing_config:
        adapter.load(workspace.workspace_id)
    assert missing_config.value.cause is WorkspaceErrorCause.ISOLATION_FAILURE


def test_internal_directory_symlink_is_allowed_but_loop_is_rejected(tmp_path: Path) -> None:
    source, baseline = _source_repository(tmp_path)
    adapter, root, _ = _adapter(tmp_path, source, "workspace")
    workspace = adapter.prepare(_identity(baseline))
    checkout = root / "workspace"
    (checkout / "target").mkdir()
    (checkout / "link").symlink_to("target", target_is_directory=True)
    assert adapter.snapshot(workspace).workspace == workspace

    (checkout / "loop").symlink_to("loop")
    with pytest.raises(WorkspaceError) as loop:
        adapter.snapshot(workspace)
    assert loop.value.cause is WorkspaceErrorCause.ISOLATION_FAILURE


def test_release_rejects_occupied_quarantine_and_non_directory_race(tmp_path: Path) -> None:
    source, baseline = _source_repository(tmp_path)
    adapter, root, _ = _adapter(tmp_path, source, "workspace")
    workspace = adapter.prepare(_identity(baseline))
    quarantine = root / ".release-workspace"
    quarantine.mkdir()
    with pytest.raises(WorkspaceError) as occupied:
        adapter.release(workspace)
    assert occupied.value.cause is WorkspaceErrorCause.STORAGE_FAILURE
    quarantine.rmdir()

    shutil.rmtree(root / "workspace")
    (root / "workspace").write_text("replacement", encoding="utf-8")
    with pytest.raises(WorkspaceError) as non_directory:
        adapter.release(workspace)
    assert non_directory.value.cause is WorkspaceErrorCause.ISOLATION_FAILURE
    assert not (root / "workspace").exists()


def test_release_failure_rolls_quarantine_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, baseline = _source_repository(tmp_path)
    adapter, root, _ = _adapter(tmp_path, source, "workspace")
    workspace = adapter.prepare(_identity(baseline))
    original_rmtree = workspace_module.shutil.rmtree

    def fail_quarantine(path: Path) -> None:
        if path.name.startswith(".release-"):
            raise OSError("injected")
        original_rmtree(path)

    monkeypatch.setattr(workspace_module.shutil, "rmtree", fail_quarantine)
    with pytest.raises(WorkspaceError) as captured:
        adapter.release(workspace)
    assert captured.value.cause is WorkspaceErrorCause.STORAGE_FAILURE
    assert (root / "workspace").is_dir()
    monkeypatch.undo()
    assert adapter.load(workspace.workspace_id) == workspace


def test_config_read_failure_and_private_mapping_defenses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, baseline = _source_repository(tmp_path)
    adapter, root, protected = _adapter(tmp_path, source, "workspace")
    workspace = adapter.prepare(_identity(baseline))
    config = root / "workspace" / ".git" / "config"
    original_read = Path.read_bytes

    def fail_config(path: Path) -> bytes:
        if path == config:
            raise OSError("injected")
        return original_read(path)

    monkeypatch.setattr(Path, "read_bytes", fail_config)
    with pytest.raises(WorkspaceError) as unreadable:
        adapter.load(workspace.workspace_id)
    assert unreadable.value.cause is WorkspaceErrorCause.STORAGE_FAILURE
    monkeypatch.undo()

    record = adapter._records[workspace.workspace_id]  # pyright: ignore[reportPrivateUsage]
    object.__setattr__(record, "path", root / "other")
    with pytest.raises(WorkspaceError) as invalid_mapping:
        adapter.load(workspace.workspace_id)
    assert invalid_mapping.value.cause is WorkspaceErrorCause.ISOLATION_FAILURE
    object.__setattr__(record, "path", protected)
    with pytest.raises(WorkspaceError) as protected_mapping:
        adapter.release(workspace)
    assert protected_mapping.value.cause is WorkspaceErrorCause.ISOLATION_FAILURE

    corrupted = object.__new__(WorkspaceId)
    object.__setattr__(corrupted, "value", "../escape")
    with pytest.raises(WorkspaceError):
        adapter._path_for(corrupted)  # pyright: ignore[reportPrivateUsage]


def test_discard_never_targets_protected_or_outside_paths(tmp_path: Path) -> None:
    source, _ = _source_repository(tmp_path)
    adapter, _, protected = _adapter(tmp_path, source, "workspace")
    marker = protected / "marker"
    marker.write_text("safe", encoding="utf-8")
    adapter._discard_unpublished(protected)  # pyright: ignore[reportPrivateUsage]
    assert marker.read_text(encoding="utf-8") == "safe"


def test_discard_failure_is_best_effort(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source, _ = _source_repository(tmp_path)
    adapter, root, _ = _adapter(tmp_path, source, "workspace")
    partial = root / "partial"
    partial.mkdir()

    def fail_remove(path: Path) -> None:
        raise OSError(path)

    monkeypatch.setattr(workspace_module.shutil, "rmtree", fail_remove)
    adapter._discard_unpublished(partial)  # pyright: ignore[reportPrivateUsage]
    assert partial.is_dir()


def test_workspace_walk_errors_fail_closed(tmp_path: Path) -> None:
    source, _ = _source_repository(tmp_path)
    adapter, _, _ = _adapter(tmp_path, source, "workspace")
    with pytest.raises(WorkspaceError) as captured:
        adapter._raise_walk_error(OSError("injected"))  # pyright: ignore[reportPrivateUsage]
    assert captured.value.cause is WorkspaceErrorCause.STORAGE_FAILURE


def test_execution_lease_blocks_release_until_coordination_finishes(tmp_path: Path) -> None:
    source, baseline = _source_repository(tmp_path)
    adapter, root, _ = _adapter(tmp_path, source, "workspace")
    workspace = adapter.prepare(_identity(baseline))
    entered = Event()
    finish_execution = Event()
    release_finished = Event()

    def hold_lease() -> None:
        with adapter.execution_lease(workspace) as path:
            assert path == root / "workspace"
            entered.set()
            assert finish_execution.wait(timeout=5)

    def release_workspace() -> None:
        adapter.release(workspace)
        release_finished.set()

    execution_thread = Thread(target=hold_lease)
    execution_thread.start()
    assert entered.wait(timeout=5)
    release_thread = Thread(target=release_workspace)
    release_thread.start()
    assert not release_finished.wait(timeout=0.05)
    finish_execution.set()
    execution_thread.join(timeout=5)
    release_thread.join(timeout=5)
    assert not execution_thread.is_alive()
    assert not release_thread.is_alive()
    assert release_finished.is_set()
    assert adapter.load(workspace.workspace_id) is None


def test_execution_lease_revalidates_workspace_after_coordination(tmp_path: Path) -> None:
    source, baseline = _source_repository(tmp_path)
    adapter, _, _ = _adapter(tmp_path, source, "workspace")
    workspace = adapter.prepare(_identity(baseline))
    outside = tmp_path / "outside"
    outside.mkdir()

    with (
        pytest.raises(WorkspaceError) as captured,
        adapter.execution_lease(workspace) as path,
    ):
        (path / "escape").symlink_to(outside, target_is_directory=True)
    assert captured.value.cause is WorkspaceErrorCause.ISOLATION_FAILURE
