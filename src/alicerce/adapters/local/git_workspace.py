"""Capability-owned local Git workspace adapter."""

import hashlib
import os
import shutil
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import cast

from alicerce.adapters.local.git_cli import ControlledGitCli, GitCliError, GitCliErrorCause
from alicerce.domain.run_identity import RunId, RunIdentity
from alicerce.domain.workspace import (
    CandidateIdentity,
    WorkspaceId,
    WorkspaceIdentity,
    bind_candidate,
)
from alicerce.ports.workspace import (
    WorkspaceError,
    WorkspaceErrorCause,
    WorkspaceIdGeneratorPort,
)


def _require_path(value: object, *, name: str) -> Path:
    if not isinstance(value, Path):
        raise TypeError(f"{name} must be Path")
    return value


def _require_instance[ValueT](value: object, *, name: str, expected: type[ValueT]) -> ValueT:
    if not isinstance(value, expected):
        raise TypeError(f"{name} must be {expected.__name__}")
    return value


def _require_tuple(value: object, *, name: str) -> tuple[object, ...]:
    if not isinstance(value, tuple):
        raise TypeError(f"{name} must be a tuple")
    return cast(tuple[object, ...], value)


@dataclass(frozen=True, slots=True)
class _WorkspaceRecord:
    identity: WorkspaceIdentity
    path: Path
    config_digest: bytes


class LocalGitWorkspace:
    """Implement ``WorkspacePort`` without exposing host paths to callers."""

    def __init__(
        self,
        *,
        source_repository: Path,
        workspace_root: Path,
        protected_roots: tuple[Path, ...],
        git: ControlledGitCli,
        id_generator: WorkspaceIdGeneratorPort,
    ) -> None:
        """Bind trusted roots, Git mechanics, and deterministic capability IDs."""
        source = self._resolve_directory(source_repository, name="source_repository")
        root = self._resolve_directory(workspace_root, name="workspace_root")
        raw_protected = _require_tuple(protected_roots, name="protected_roots")
        protected = tuple(
            self._resolve_directory(path, name="protected_root") for path in raw_protected
        )
        git = _require_instance(git, name="git", expected=ControlledGitCli)
        generator = cast(object, id_generator)
        if not callable(getattr(generator, "new_workspace_id", None)):
            raise TypeError("id_generator must provide new_workspace_id")

        all_protected = (source, *protected)
        for protected_root in all_protected:
            if self._overlaps(root, protected_root):
                raise ValueError("workspace_root must be disjoint from protected roots")

        self._source = source
        self._root = root
        self._protected = all_protected
        self._git = git
        self._id_generator = id_generator
        self._records: dict[WorkspaceId, _WorkspaceRecord] = {}
        self._run_index: dict[RunId, WorkspaceId] = {}
        self._lock = RLock()

    def prepare(self, identity: RunIdentity) -> WorkspaceIdentity:
        """Materialize and publish one exact baseline under a new capability."""
        identity = _require_instance(identity, name="identity", expected=RunIdentity)
        with self._lock:
            self._assert_root_integrity()
            if identity.run_id in self._run_index:
                raise WorkspaceError(WorkspaceErrorCause.ALREADY_EXISTS, identity.run_id.value)

            workspace_id = _require_instance(
                self._id_generator.new_workspace_id(),
                name="workspace_id",
                expected=WorkspaceId,
            )
            destination = self._path_for(workspace_id)
            if workspace_id in self._records or destination.exists() or destination.is_symlink():
                raise WorkspaceError(WorkspaceErrorCause.ALREADY_EXISTS, workspace_id.value)

            workspace = WorkspaceIdentity(
                workspace_id=workspace_id,
                run_id=identity.run_id,
                baseline_sha=identity.baseline_sha,
            )
            try:
                self._git.materialize_baseline(
                    self._source,
                    destination,
                    identity.baseline_sha,
                )
                self._validate_symlinks(destination)
                config_digest = self._config_digest(destination)
                self._git.verify_baseline(destination, identity.baseline_sha)
            except GitCliError as error:
                self._discard_unpublished(destination)
                raise self._translate_git_error(error) from error
            except WorkspaceError:
                self._discard_unpublished(destination)
                raise
            except OSError as error:
                self._discard_unpublished(destination)
                raise WorkspaceError(
                    WorkspaceErrorCause.STORAGE_FAILURE,
                    "workspace preparation failed",
                ) from error

            record = _WorkspaceRecord(workspace, destination, config_digest)
            self._records[workspace_id] = record
            self._run_index[identity.run_id] = workspace_id
            return workspace

    def load(self, workspace_id: WorkspaceId) -> WorkspaceIdentity | None:
        """Resolve and revalidate an existing in-process capability."""
        workspace_id = _require_instance(
            workspace_id,
            name="workspace_id",
            expected=WorkspaceId,
        )
        with self._lock:
            record = self._records.get(workspace_id)
            if record is None:
                return None
            self._validate_record(record)
            return record.identity

    def snapshot(self, workspace: WorkspaceIdentity) -> CandidateIdentity:
        """Return a trusted Git tree identity without changing the real index."""
        workspace = _require_instance(
            workspace,
            name="workspace",
            expected=WorkspaceIdentity,
        )
        with self._lock:
            record = self._require_record(workspace)
            self._validate_record(record)
            try:
                candidate_sha = self._git.snapshot_candidate(record.path)
                self._validate_record(record)
            except GitCliError as error:
                raise self._translate_git_error(error) from error
            return bind_candidate(record.identity, candidate_sha)

    def release(self, workspace: WorkspaceIdentity) -> None:
        """Atomically detach and safely remove only the recorded workspace."""
        workspace = _require_instance(
            workspace,
            name="workspace",
            expected=WorkspaceIdentity,
        )
        with self._lock:
            record = self._records.get(workspace.workspace_id)
            if record is None:
                return
            if record.identity != workspace:
                raise WorkspaceError(WorkspaceErrorCause.CONFLICT, workspace.workspace_id.value)
            self._assert_root_integrity()
            expected = self._path_for(workspace.workspace_id)
            if record.path != expected or self._is_protected(record.path):
                raise WorkspaceError(
                    WorkspaceErrorCause.ISOLATION_FAILURE,
                    "recorded workspace path is outside its capability root",
                )
            quarantine = self._root / f".release-{workspace.workspace_id.value}"
            if not record.path.exists() and not record.path.is_symlink():
                if quarantine.exists() or quarantine.is_symlink():
                    try:
                        if quarantine.is_symlink() or not quarantine.is_dir():
                            quarantine.unlink()
                        else:
                            shutil.rmtree(quarantine)
                    except OSError as error:
                        raise WorkspaceError(
                            WorkspaceErrorCause.STORAGE_FAILURE,
                            "workspace quarantine recovery failed",
                        ) from error
                self._forget(record)
                return

            if quarantine.exists() or quarantine.is_symlink():
                raise WorkspaceError(
                    WorkspaceErrorCause.STORAGE_FAILURE,
                    "release quarantine is occupied",
                )
            try:
                record.path.rename(quarantine)
                if quarantine.is_symlink():
                    quarantine.unlink()
                    self._forget(record)
                    raise WorkspaceError(
                        WorkspaceErrorCause.ISOLATION_FAILURE,
                        "workspace path was replaced by a symlink",
                    )
                if not quarantine.is_dir():
                    quarantine.unlink()
                    self._forget(record)
                    raise WorkspaceError(
                        WorkspaceErrorCause.ISOLATION_FAILURE,
                        "workspace path was replaced by a non-directory",
                    )
                shutil.rmtree(quarantine)
            except WorkspaceError:
                raise
            except OSError as error:
                if quarantine.exists() and not record.path.exists():
                    with suppress(OSError):
                        quarantine.rename(record.path)
                raise WorkspaceError(
                    WorkspaceErrorCause.STORAGE_FAILURE,
                    "workspace release failed",
                ) from error
            self._forget(record)

    @staticmethod
    def _resolve_directory(value: object, *, name: str) -> Path:
        path = _require_path(value, name=name)
        if not path.is_absolute() or path.is_symlink():
            raise ValueError(f"{name} must be an absolute non-symlink directory")
        try:
            resolved = path.resolve(strict=True)
        except OSError as error:
            raise ValueError(f"{name} must exist") from error
        if not resolved.is_dir():
            raise ValueError(f"{name} must be a directory")
        return resolved

    @staticmethod
    def _overlaps(left: Path, right: Path) -> bool:
        return left == right or left.is_relative_to(right) or right.is_relative_to(left)

    def _assert_root_integrity(self) -> None:
        try:
            resolved = self._root.resolve(strict=True)
        except OSError as error:
            raise WorkspaceError(
                WorkspaceErrorCause.STORAGE_FAILURE,
                "workspace root is unavailable",
            ) from error
        if self._root.is_symlink() or not self._root.is_dir() or resolved != self._root:
            raise WorkspaceError(
                WorkspaceErrorCause.ISOLATION_FAILURE,
                "workspace root integrity check failed",
            )

    def _path_for(self, workspace_id: WorkspaceId) -> Path:
        path = self._root / workspace_id.value
        if path.parent != self._root:
            raise WorkspaceError(
                WorkspaceErrorCause.ISOLATION_FAILURE,
                "workspace capability escaped its root",
            )
        return path

    def _require_record(self, workspace: WorkspaceIdentity) -> _WorkspaceRecord:
        record = self._records.get(workspace.workspace_id)
        if record is None:
            raise WorkspaceError(WorkspaceErrorCause.NOT_FOUND, workspace.workspace_id.value)
        if record.identity != workspace:
            raise WorkspaceError(WorkspaceErrorCause.CONFLICT, workspace.workspace_id.value)
        return record

    def _validate_record(self, record: _WorkspaceRecord) -> None:
        self._assert_root_integrity()
        if record.path != self._path_for(record.identity.workspace_id):
            raise WorkspaceError(
                WorkspaceErrorCause.ISOLATION_FAILURE,
                "workspace mapping integrity check failed",
            )
        if record.path.is_symlink() or not record.path.is_dir() or self._is_protected(record.path):
            raise WorkspaceError(
                WorkspaceErrorCause.ISOLATION_FAILURE,
                "workspace directory integrity check failed",
            )
        self._validate_symlinks(record.path)
        if self._config_digest(record.path) != record.config_digest:
            raise WorkspaceError(
                WorkspaceErrorCause.ISOLATION_FAILURE,
                "workspace Git configuration changed",
            )
        try:
            self._git.verify_baseline(record.path, record.identity.baseline_sha)
        except GitCliError as error:
            raise self._translate_git_error(error) from error

    def _validate_symlinks(self, workspace: Path) -> None:
        for current, directories, filenames in os.walk(
            workspace,
            followlinks=False,
            onerror=self._raise_walk_error,
        ):
            current_path = Path(current)
            if current_path == workspace:
                directories[:] = [name for name in directories if name != ".git"]
            for name in (*directories, *filenames):
                path = current_path / name
                if not path.is_symlink():
                    continue
                try:
                    target = path.resolve(strict=True)
                except (OSError, RuntimeError) as error:
                    raise WorkspaceError(
                        WorkspaceErrorCause.ISOLATION_FAILURE,
                        "workspace contains an invalid symlink",
                    ) from error
                if not target.is_relative_to(workspace):
                    raise WorkspaceError(
                        WorkspaceErrorCause.ISOLATION_FAILURE,
                        "workspace symlink escapes its root",
                    )
                if name in directories:
                    directories.remove(name)

    @staticmethod
    def _raise_walk_error(error: OSError) -> None:
        raise WorkspaceError(
            WorkspaceErrorCause.STORAGE_FAILURE,
            "workspace content cannot be inspected",
        ) from error

    @staticmethod
    def _config_digest(workspace: Path) -> bytes:
        config = workspace / ".git" / "config"
        if config.is_symlink() or not config.is_file():
            raise WorkspaceError(
                WorkspaceErrorCause.ISOLATION_FAILURE,
                "workspace Git configuration is unavailable",
            )
        try:
            return hashlib.sha256(config.read_bytes()).digest()
        except OSError as error:
            raise WorkspaceError(
                WorkspaceErrorCause.STORAGE_FAILURE,
                "workspace Git configuration cannot be read",
            ) from error

    def _is_protected(self, path: Path) -> bool:
        return any(self._overlaps(path, protected) for protected in self._protected)

    def _discard_unpublished(self, path: Path) -> None:
        if path.parent != self._root or self._is_protected(path):
            return
        try:
            if path.is_symlink() or (path.exists() and not path.is_dir()):
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path)
        except OSError:
            pass

    def _forget(self, record: _WorkspaceRecord) -> None:
        self._records.pop(record.identity.workspace_id, None)
        self._run_index.pop(record.identity.run_id, None)

    @staticmethod
    def _translate_git_error(error: GitCliError) -> WorkspaceError:
        isolation_causes = {
            GitCliErrorCause.INVALID_CONFIGURATION,
            GitCliErrorCause.INVALID_PATH,
            GitCliErrorCause.DESTINATION_EXISTS,
            GitCliErrorCause.BASELINE_MISMATCH,
        }
        cause = (
            WorkspaceErrorCause.ISOLATION_FAILURE
            if error.cause in isolation_causes
            else WorkspaceErrorCause.STORAGE_FAILURE
        )
        return WorkspaceError(cause, "controlled Git workspace operation failed")
