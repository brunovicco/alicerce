"""Transactional SQLite implementation of the trusted state-store port."""

import sqlite3
from pathlib import Path
from typing import Final

from alicerce.adapters.local.state_serialization import (
    StateSerializationError,
    deserialize_checkpoint,
    deserialize_run_identity,
    deserialize_transition,
    serialize_checkpoint,
    serialize_run_identity,
    serialize_transition,
)
from alicerce.domain.lifecycle import LifecycleTransition, advance_lifecycle
from alicerce.domain.run_identity import RunId
from alicerce.domain.state import (
    RunCheckpoint,
    StateUpdate,
    create_initial_checkpoint,
)
from alicerce.ports.state_store import (
    StateStoreError,
    StateStoreErrorCause,
)

_SCHEMA_VERSION: Final = 1
_SCHEMA: Final = (
    """CREATE TABLE alicerce_runs (
    run_id TEXT PRIMARY KEY,
    identity BLOB NOT NULL CHECK(typeof(identity) = 'blob'),
    checkpoint BLOB NOT NULL CHECK(typeof(checkpoint) = 'blob')
) STRICT""",
    """CREATE TABLE alicerce_transitions (
    run_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK(revision > 0),
    transition BLOB NOT NULL CHECK(typeof(transition) = 'blob'),
    PRIMARY KEY (run_id, revision),
    FOREIGN KEY (run_id) REFERENCES alicerce_runs(run_id) ON DELETE RESTRICT
) STRICT""",
)


def _require_instance[ValueT](value: object, *, name: str, expected: type[ValueT]) -> ValueT:
    if not isinstance(value, expected):
        raise TypeError(f"{name} must be {expected.__name__}")
    return value


class SQLiteStateStore:
    """Local durable state store with whole-checkpoint CAS semantics."""

    def __init__(self, database: object, *, timeout_seconds: object = 5.0) -> None:
        """Open or initialize one schema-versioned SQLite database."""
        if not isinstance(database, (str, Path)):
            raise TypeError("database must be str or Path")
        database_text = str(database)
        if not database_text:
            raise ValueError("database must be non-empty")
        if database_text == ":memory:":
            raise ValueError("database must be a durable filesystem path")
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
            raise TypeError("timeout_seconds must be numeric")
        if timeout_seconds < 0:
            raise ValueError("timeout_seconds must be non-negative")
        self._database = database_text
        self._timeout_seconds = float(timeout_seconds)
        self._initialize_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self._database,
            timeout=self._timeout_seconds,
            isolation_level=None,
        )
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize_schema(self) -> None:
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect()
            connection.execute("BEGIN IMMEDIATE")
            version_row = connection.execute("PRAGMA user_version").fetchone()
            version = int(version_row[0]) if version_row is not None else -1
            if version == 0:
                for statement in _SCHEMA:
                    connection.execute(statement)
                connection.execute("PRAGMA user_version = 1")
            elif version != _SCHEMA_VERSION:
                raise StateStoreError(
                    StateStoreErrorCause.CORRUPT,
                    f"unsupported SQLite state schema version: {version}",
                )
            connection.commit()
        except StateStoreError:
            if connection is not None:
                connection.rollback()
            raise
        except sqlite3.Error as error:
            if connection is not None:
                connection.rollback()
            raise self._storage_failure(error) from error
        finally:
            if connection is not None:
                connection.close()

    @staticmethod
    def _storage_failure(error: sqlite3.Error) -> StateStoreError:
        return StateStoreError(StateStoreErrorCause.STORAGE_FAILURE, str(error))

    @staticmethod
    def _corrupt(detail: str, error: Exception | None = None) -> StateStoreError:
        failure = StateStoreError(StateStoreErrorCause.CORRUPT, detail)
        if error is not None:
            failure.__cause__ = error
        return failure

    @staticmethod
    def _blob(value: object, *, name: str) -> bytes:
        if not isinstance(value, bytes):
            raise SQLiteStateStore._corrupt(f"{name} is not stored as bytes")
        return value

    def _validated_run(
        self,
        connection: sqlite3.Connection,
        run_id: RunId,
    ) -> tuple[RunCheckpoint, tuple[LifecycleTransition, ...]] | None:
        row = connection.execute(
            "SELECT identity, checkpoint FROM alicerce_runs WHERE run_id = ?",
            (run_id.value,),
        ).fetchone()
        if row is None:
            return None
        try:
            identity = deserialize_run_identity(self._blob(row[0], name="identity"))
            stored = deserialize_checkpoint(self._blob(row[1], name="checkpoint"))
            if identity != stored.identity or identity.run_id != run_id:
                raise self._corrupt("stored identity does not match checkpoint or lookup key")

            checkpoint = create_initial_checkpoint(identity)
            events: list[LifecycleTransition] = []
            rows = connection.execute(
                """
                SELECT revision, transition
                FROM alicerce_transitions
                WHERE run_id = ?
                ORDER BY revision
                """,
                (run_id.value,),
            ).fetchall()
            for expected_revision, event_row in enumerate(rows, start=1):
                revision = event_row[0]
                if type(revision) is not int or revision != expected_revision:
                    raise self._corrupt("transition journal has a revision gap")
                event = deserialize_transition(self._blob(event_row[1], name="transition"))
                generated = advance_lifecycle(
                    checkpoint.lifecycle,
                    to_state=event.to_state,
                    occurred_at=event.occurred_at,
                    actor=event.actor,
                    final_state=event.final_state,
                )
                if generated.transition != event:
                    raise self._corrupt("transition journal does not form one valid history")
                checkpoint = RunCheckpoint(
                    identity=identity,
                    lifecycle=generated.lifecycle,
                )
                events.append(event)
            if checkpoint != stored:
                raise self._corrupt("stored checkpoint does not match transition history")
            return checkpoint, tuple(events)
        except StateStoreError:
            raise
        except (StateSerializationError, TypeError, ValueError) as error:
            raise self._corrupt("stored run state is invalid", error) from error

    def initialize(self, checkpoint: object) -> None:
        """Persist the identity-derived initial checkpoint exclusively."""
        trusted = _require_instance(
            checkpoint,
            name="checkpoint",
            expected=RunCheckpoint,
        )
        if trusted != create_initial_checkpoint(trusted.identity):
            raise StateStoreError(
                StateStoreErrorCause.CONFLICT,
                "checkpoint must be the identity-derived initial state",
            )
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect()
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT 1 FROM alicerce_runs WHERE run_id = ?",
                (trusted.identity.run_id.value,),
            ).fetchone()
            if existing is not None:
                raise StateStoreError(
                    StateStoreErrorCause.ALREADY_EXISTS,
                    trusted.identity.run_id.value,
                )
            connection.execute(
                "INSERT INTO alicerce_runs(run_id, identity, checkpoint) VALUES (?, ?, ?)",
                (
                    trusted.identity.run_id.value,
                    serialize_run_identity(trusted.identity),
                    serialize_checkpoint(trusted),
                ),
            )
            connection.commit()
        except StateStoreError:
            if connection is not None:
                connection.rollback()
            raise
        except sqlite3.Error as error:
            if connection is not None:
                connection.rollback()
            raise self._storage_failure(error) from error
        finally:
            if connection is not None:
                connection.close()

    def load(self, run_id: object) -> RunCheckpoint | None:
        """Load and validate the complete persisted history for one run."""
        trusted = _require_instance(run_id, name="run_id", expected=RunId)
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect()
            validated = self._validated_run(connection, trusted)
            return validated[0] if validated is not None else None
        except StateStoreError:
            raise
        except sqlite3.Error as error:
            raise self._storage_failure(error) from error
        finally:
            if connection is not None:
                connection.close()

    def compare_and_append(self, update: object) -> RunCheckpoint:
        """Atomically append one event when the complete checkpoint matches."""
        trusted = _require_instance(update, name="update", expected=StateUpdate)
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect()
            connection.execute("BEGIN IMMEDIATE")
            validated = self._validated_run(connection, trusted.expected.identity.run_id)
            if validated is None:
                raise StateStoreError(
                    StateStoreErrorCause.NOT_FOUND,
                    trusted.expected.identity.run_id.value,
                )
            current, _ = validated
            if current != trusted.expected:
                raise StateStoreError(
                    StateStoreErrorCause.CONFLICT,
                    trusted.expected.identity.run_id.value,
                )

            expected_bytes = serialize_checkpoint(trusted.expected)
            next_checkpoint = trusted.next_checkpoint
            connection.execute(
                """
                INSERT INTO alicerce_transitions(run_id, revision, transition)
                VALUES (?, ?, ?)
                """,
                (
                    trusted.expected.identity.run_id.value,
                    trusted.advance.transition.revision,
                    serialize_transition(trusted.advance.transition),
                ),
            )
            cursor = connection.execute(
                """
                UPDATE alicerce_runs
                SET checkpoint = ?
                WHERE run_id = ? AND checkpoint = ?
                """,
                (
                    serialize_checkpoint(next_checkpoint),
                    trusted.expected.identity.run_id.value,
                    expected_bytes,
                ),
            )
            if cursor.rowcount != 1:
                raise StateStoreError(
                    StateStoreErrorCause.CONFLICT,
                    trusted.expected.identity.run_id.value,
                )
            connection.commit()
            return next_checkpoint
        except StateStoreError:
            if connection is not None:
                connection.rollback()
            raise
        except sqlite3.Error as error:
            if connection is not None:
                connection.rollback()
            raise self._storage_failure(error) from error
        finally:
            if connection is not None:
                connection.close()

    def history(self, run_id: object) -> tuple[LifecycleTransition, ...]:
        """Load and validate the immutable transition history for one run."""
        trusted = _require_instance(run_id, name="run_id", expected=RunId)
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect()
            validated = self._validated_run(connection, trusted)
            if validated is None:
                raise StateStoreError(StateStoreErrorCause.NOT_FOUND, trusted.value)
            return validated[1]
        except StateStoreError:
            raise
        except sqlite3.Error as error:
            raise self._storage_failure(error) from error
        finally:
            if connection is not None:
                connection.close()
