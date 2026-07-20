"""Integration tests for controlled local Git baseline materialization."""

import shutil
import stat
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

from alicerce.adapters.local.git_cli import (
    ControlledGitCli,
    GitCliError,
    GitCliErrorCause,
    MaterializedBaseline,
)
from alicerce.domain.run_identity import BaselineSha


class InspectableControlledGitCli(ControlledGitCli):
    """Test-only access to the bounded capture clock edge."""

    def capture(self, process: subprocess.Popen[bytes]) -> tuple[bytes, bytes]:
        return self._capture_bounded(process)


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
    source = tmp_path / "trusted-source"
    source.mkdir()
    _run_git(source, "init", "--initial-branch=main")
    _run_git(source, "config", "user.name", "Alicerce Tests")
    _run_git(source, "config", "user.email", "tests@alicerce.invalid")
    (source / "payload.txt").write_text("baseline\n", encoding="utf-8")
    _run_git(source, "add", "payload.txt")
    _run_git(source, "commit", "-m", "baseline")
    return source, BaselineSha(_run_git(source, "rev-parse", "HEAD"))


def _script(
    tmp_path: Path,
    body: str,
    *,
    name: str = "controlled-git",
) -> Path:
    executable = tmp_path / name
    executable.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    return executable


def test_materializes_exact_detached_baseline_without_remote(tmp_path: Path) -> None:
    source, baseline = _source_repository(tmp_path)
    destination = tmp_path / "candidate"
    result = ControlledGitCli(_git()).materialize_baseline(source, destination, baseline)
    assert result == MaterializedBaseline(destination, baseline)
    assert _run_git(destination, "rev-parse", "HEAD") == baseline.value
    symbolic = subprocess.run(  # noqa: S603
        (str(_git()), "-C", str(destination), "symbolic-ref", "-q", "HEAD"),
        check=False,
        stdout=subprocess.PIPE,
    )
    assert symbolic.returncode == 1
    assert _run_git(destination, "remote") == ""
    assert (destination / "payload.txt").read_text(encoding="utf-8") == "baseline\n"
    assert not (destination / ".git" / "objects" / "info" / "alternates").exists()


def test_candidate_checkout_does_not_share_source_object_files(tmp_path: Path) -> None:
    source, baseline = _source_repository(tmp_path)
    destination = tmp_path / "candidate"
    ControlledGitCli(_git()).materialize_baseline(source, destination, baseline)
    source_objects = {
        (path.stat().st_dev, path.stat().st_ino)
        for path in (source / ".git" / "objects").rglob("*")
        if path.is_file()
    }
    destination_objects = {
        (path.stat().st_dev, path.stat().st_ino)
        for path in (destination / ".git" / "objects").rglob("*")
        if path.is_file()
    }
    assert source_objects
    assert destination_objects
    assert source_objects.isdisjoint(destination_objects)


def test_invalid_baseline_fails_closed_and_discards_partial_clone(tmp_path: Path) -> None:
    source, _ = _source_repository(tmp_path)
    destination = tmp_path / "candidate"
    with pytest.raises(GitCliError) as captured:
        ControlledGitCli(_git()).materialize_baseline(source, destination, BaselineSha("f" * 40))
    assert captured.value.cause is GitCliErrorCause.COMMAND_FAILED
    assert not destination.exists()


def test_mismatched_resolved_head_fails_closed(tmp_path: Path) -> None:
    source, baseline = _source_repository(tmp_path)
    destination = tmp_path / "candidate"
    mismatching = _script(
        tmp_path,
        'if [ "$1" = "clone" ]; then mkdir "$7"; fi\n'
        'if [ "$3" = "rev-parse" ]; then printf "%040d\\n" 0; fi',
    )
    with pytest.raises(GitCliError) as captured:
        ControlledGitCli(mismatching).materialize_baseline(source, destination, baseline)
    assert captured.value.cause is GitCliErrorCause.BASELINE_MISMATCH
    assert not destination.exists()


@pytest.mark.parametrize("which", ["source", "destination"])
def test_relative_paths_are_rejected_before_process_creation(tmp_path: Path, which: str) -> None:
    source, baseline = _source_repository(tmp_path)
    destination = tmp_path / "candidate"
    source = Path("relative") if which == "source" else source
    destination = Path("relative") if which == "destination" else destination
    with pytest.raises(GitCliError) as captured:
        ControlledGitCli(_git()).materialize_baseline(source, destination, baseline)
    assert captured.value.cause is GitCliErrorCause.INVALID_PATH


def test_existing_or_nested_destination_is_rejected(tmp_path: Path) -> None:
    source, baseline = _source_repository(tmp_path)
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(GitCliError) as occupied:
        ControlledGitCli(_git()).materialize_baseline(source, existing, baseline)
    assert occupied.value.cause is GitCliErrorCause.DESTINATION_EXISTS
    with pytest.raises(GitCliError) as nested:
        ControlledGitCli(_git()).materialize_baseline(source, source / "candidate", baseline)
    assert nested.value.cause is GitCliErrorCause.INVALID_PATH


def test_missing_parent_file_source_and_root_destination_are_rejected(tmp_path: Path) -> None:
    source, baseline = _source_repository(tmp_path)
    with pytest.raises(GitCliError) as missing_parent:
        ControlledGitCli(_git()).materialize_baseline(
            source, tmp_path / "missing" / "candidate", baseline
        )
    assert missing_parent.value.cause is GitCliErrorCause.INVALID_PATH

    source_file = tmp_path / "source-file"
    source_file.write_text("not a repository", encoding="utf-8")
    with pytest.raises(GitCliError) as not_directory:
        ControlledGitCli(_git()).materialize_baseline(source_file, tmp_path / "candidate", baseline)
    assert not_directory.value.cause is GitCliErrorCause.INVALID_PATH

    with pytest.raises(GitCliError) as invalid_name:
        ControlledGitCli(_git()).materialize_baseline(source, Path("/"), baseline)
    assert invalid_name.value.cause is GitCliErrorCause.INVALID_PATH


def test_executable_and_limits_are_validated(tmp_path: Path) -> None:
    with pytest.raises(GitCliError):
        ControlledGitCli(Path("git"))
    with pytest.raises(GitCliError) as missing:
        ControlledGitCli(tmp_path / "missing")
    assert missing.value.cause is GitCliErrorCause.INVALID_CONFIGURATION
    inert = tmp_path / "inert"
    inert.write_text("inert", encoding="utf-8")
    with pytest.raises(GitCliError):
        ControlledGitCli(inert)
    with pytest.raises(TypeError):
        ControlledGitCli(str(_git()))  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        ControlledGitCli(_git(), timeout_seconds=True)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        ControlledGitCli(_git(), max_output_bytes=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        ControlledGitCli(_git(), timeout_seconds=0)
    with pytest.raises(ValueError):
        ControlledGitCli(_git(), max_output_bytes=0)


def test_timeout_and_output_limit_fail_closed(tmp_path: Path) -> None:
    source, baseline = _source_repository(tmp_path)
    sleeper = _script(tmp_path, "sleep 1", name="sleeping-git")
    with pytest.raises(GitCliError) as timed_out:
        ControlledGitCli(sleeper, timeout_seconds=0.01).materialize_baseline(
            source, tmp_path / "timed-out", baseline
        )
    assert timed_out.value.cause is GitCliErrorCause.TIMEOUT
    noisy = _script(tmp_path, "printf 'output-too-large'", name="noisy-git")

    with pytest.raises(GitCliError) as excessive:
        ControlledGitCli(noisy, max_output_bytes=4).materialize_baseline(
            source, tmp_path / "excessive", baseline
        )
    assert excessive.value.cause is GitCliErrorCause.OUTPUT_LIMIT


def test_spawn_control_directory_and_stdout_failures_are_typed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, baseline = _source_repository(tmp_path)
    vanished = _script(tmp_path, "exit 0")
    cli = ControlledGitCli(vanished)
    vanished.unlink()
    with pytest.raises(GitCliError) as spawn:
        cli.materialize_baseline(source, tmp_path / "spawn", baseline)
    assert spawn.value.cause is GitCliErrorCause.COMMAND_FAILED

    def fail_control_directory(*args: object, **kwargs: object) -> tempfile.TemporaryDirectory[str]:
        raise OSError("control directory unavailable")

    monkeypatch.setattr(tempfile, "TemporaryDirectory", fail_control_directory)
    with pytest.raises(GitCliError) as control:
        ControlledGitCli(_git()).materialize_baseline(source, tmp_path / "control", baseline)
    assert control.value.cause is GitCliErrorCause.COMMAND_FAILED


def test_non_utf8_stdout_fails_closed(tmp_path: Path) -> None:
    source, baseline = _source_repository(tmp_path)
    invalid = _script(tmp_path, "printf '\\377'")
    with pytest.raises(GitCliError) as captured:
        ControlledGitCli(invalid).materialize_baseline(
            source, tmp_path / "invalid-output", baseline
        )
    assert captured.value.cause is GitCliErrorCause.COMMAND_FAILED


def test_expired_deadline_is_checked_before_waiting_for_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sleeper = _script(tmp_path, "sleep 1")
    process = subprocess.Popen(  # noqa: S603
        (str(sleeper),),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    readings = iter((0.0, 2.0))
    monkeypatch.setattr(time, "monotonic", lambda: next(readings))
    with pytest.raises(GitCliError) as captured:
        InspectableControlledGitCli(sleeper, timeout_seconds=1).capture(process)
    assert captured.value.cause is GitCliErrorCause.TIMEOUT


def test_inherited_git_environment_cannot_redirect_operation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, baseline = _source_repository(tmp_path)
    destination = tmp_path / "candidate"
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "attacker"))
    monkeypatch.setenv("GIT_WORK_TREE", str(tmp_path / "attacker-tree"))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "attacker-config"))
    ControlledGitCli(_git()).materialize_baseline(source, destination, baseline)
    assert _run_git(destination, "rev-parse", "HEAD") == baseline.value


def test_result_rejects_type_confusion(tmp_path: Path) -> None:
    baseline = BaselineSha("a" * 40)
    with pytest.raises(TypeError):
        MaterializedBaseline("repository", baseline)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        MaterializedBaseline(Path("repository"), baseline)
    with pytest.raises(TypeError):
        MaterializedBaseline(tmp_path, object())  # type: ignore[arg-type]


def test_controlled_git_cli_exposes_no_generic_command_method() -> None:
    public_methods = {
        name
        for name in dir(ControlledGitCli)
        if not name.startswith("_") and callable(getattr(ControlledGitCli, name))
    }
    assert public_methods == {"materialize_baseline"}
