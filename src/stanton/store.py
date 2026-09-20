"""Atomic working revisions and immutable, compressed run artifacts."""

import gzip
import json
import sqlite3
import zlib
from contextlib import contextmanager
from pathlib import Path

from .common import canonical, digest, identifier, now, require

DDL = """
CREATE TABLE revisions (
 revision INTEGER PRIMARY KEY, body TEXT NOT NULL, sha256 TEXT NOT NULL,
 operation TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE runs (
 id TEXT PRIMARY KEY, revision INTEGER NOT NULL REFERENCES revisions(revision),
 body BLOB NOT NULL, sha256 TEXT NOT NULL, created_at TEXT NOT NULL
);
"""


class Store:
    def __init__(self, project):
        self.root = Path(project).resolve()
        self.path = self.root / ".stanton" / "state.sqlite"

    def init(self, state, *, initial_record=None):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        require(not self.path.exists(), "Project already exists.", "project_exists")
        with self.path.open("xb"):
            pass
        with sqlite3.connect(self.path) as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript(DDL)
            for table in ("revisions", "runs"):
                for op in ("UPDATE", "DELETE"):
                    c.execute(f"CREATE TRIGGER immutable_{table}_{op} BEFORE {op} ON {table} "
                              "BEGIN SELECT RAISE(ABORT, 'immutable history'); END")
            c.execute("INSERT INTO revisions VALUES (?,?,?,?,?)", (1, canonical(state), digest(state),
                      initial_record["operation"] if initial_record else "init",
                      initial_record["created_at"] if initial_record else now()))
        return {"project": str(self.root), "revision": 1}

    @contextmanager
    def connect(self, write=False):
        require(self.path.exists(), "Project is not initialized; run stanton init PATH.", "uninitialized_project")
        c = sqlite3.connect(self.path.as_uri() + ("?mode=rw" if write else "?mode=ro"), uri=True, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        try:
            c.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    @staticmethod
    def _state(c, revision=None):
        row = c.execute("SELECT * FROM revisions WHERE (? IS NULL OR revision=?) ORDER BY revision DESC LIMIT 1",
                        (revision, revision)).fetchone()
        require(row is not None, "Unknown project revision.", "not_found")
        state = json.loads(row["body"])
        require(digest(state) == row["sha256"], "State integrity check failed.", "integrity_error")
        return state, row["revision"]

    def read(self, revision=None):
        with self.connect() as c:
            return self._state(c, revision)

    def edit(self, operation, mutate, expected_revision=None):
        with self.connect(write=True) as c:
            state, revision = self._state(c)
            require(expected_revision is None or expected_revision == revision,
                    f"Expected revision {expected_revision}; current revision is {revision}.", "stale_revision")
            result = mutate(state)
            c.execute("INSERT INTO revisions VALUES (?,?,?,?,?)",
                      (revision + 1, canonical(state), digest(state), operation, now()))
        return {"revision": revision + 1, **(result or {})}

    def put_run(self, result, revision):
        run_id = identifier("run")
        result = {**result, "id": run_id, "revision": revision, "created_at": now()}
        with self.connect(write=True) as c:
            self._state(c, revision)
            c.execute("INSERT INTO runs VALUES (?,?,?,?,?)",
                      (run_id, revision, zlib.compress(canonical(result).encode()), digest(result), result["created_at"]))
        return result

    @staticmethod
    def _run(row):
        value = json.loads(zlib.decompress(row["body"]))
        require(digest(value) == row["sha256"], "Run integrity check failed.", "integrity_error")
        return value

    def run(self, run_id=None, target=None):
        with self.connect() as c:
            rows = c.execute("SELECT * FROM runs WHERE (? IS NULL OR id=?) ORDER BY rowid DESC", (run_id, run_id))
            for row in rows:
                result = self._run(row)
                if target is None or result["target"] == target:
                    return result
        require(False, "No matching sample run; run stanton sample first.", "not_found")

    def export(self, path):
        destination = Path(path)
        with self.connect() as c:
            revisions = [dict(row) for row in c.execute("SELECT * FROM revisions ORDER BY revision")]
            for row in revisions:
                body = json.loads(row["body"])
                require(digest(body) == row["sha256"], "State integrity check failed.", "integrity_error")
                row["body"] = body
            runs = [self._run(row) for row in c.execute("SELECT * FROM runs ORDER BY rowid")]
        data = {"schema_version": 1, "revisions": revisions, "runs": runs}
        payload = {"data": data, "sha256": digest(data)}
        with destination.open("xb") as f:
            f.write(gzip.compress(canonical(payload).encode(), mtime=0))
        return {"path": str(destination.resolve()), "revisions": len(revisions), "runs": len(runs), "sha256": digest(data)}

    def restore(self, path, validate_state, validate_run, validate_history=None, validate_artifacts=None):
        require(not self.path.exists(), "Load requires an uninitialized destination project.", "project_exists")
        payload = json.loads(gzip.decompress(Path(path).read_bytes()))
        data = payload["data"]
        require(digest(data) == payload["sha256"] and data["schema_version"] == 1,
                "Invalid archive digest or schema version.", "integrity_error")
        revisions = data["revisions"]
        require(revisions and [r["revision"] for r in revisions] == list(range(1, len(revisions) + 1)),
                "Archive revisions must be consecutive.")
        for row in revisions:
            require(digest(row["body"]) == row["sha256"], "Invalid revision digest.", "integrity_error")
            require(isinstance(row["operation"], str) and isinstance(row["created_at"], str), "Invalid revision metadata.")
            validate_state(row["body"])
        if validate_history:
            validate_history([row["body"] for row in revisions])
        ids = set()
        for run in data["runs"]:
            require(run["id"] not in ids and 1 <= run["revision"] <= len(revisions), "Invalid run identity or revision.")
            require(isinstance(run["id"], str) and isinstance(run["created_at"], str), "Invalid run metadata.")
            ids.add(run["id"])
            validate_run(run, revisions[run["revision"] - 1]["body"])
        if validate_artifacts:
            validate_artifacts([row["body"] for row in revisions], data["runs"])
        self.init(revisions[0]["body"], initial_record=revisions[0])
        with self.connect(write=True) as c:
            for row in revisions[1:]:
                c.execute("INSERT INTO revisions VALUES (?,?,?,?,?)",
                          (row["revision"], canonical(row["body"]), row["sha256"], row["operation"], row["created_at"]))
            for run in data["runs"]:
                c.execute("INSERT INTO runs VALUES (?,?,?,?,?)", (run["id"], run["revision"],
                          zlib.compress(canonical(run).encode()), digest(run), run["created_at"]))
        return {"project": str(self.root), "revision": len(revisions), "runs": len(ids)}

    def validate(self, validate_state, validate_run, validate_history=None, validate_artifacts=None):
        with self.connect() as c:
            require(c.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "SQLite integrity check failed.")
            revisions = c.execute("SELECT revision FROM revisions ORDER BY revision").fetchall()
            states = []
            for row in revisions:
                state, _ = self._state(c, row["revision"])
                validate_state(state)
                states.append(state)
            if validate_history:
                validate_history(states)
            runs = c.execute("SELECT * FROM runs ORDER BY rowid").fetchall()
            artifacts = []
            for row in runs:
                run = self._run(row)
                state, _ = self._state(c, run["revision"])
                validate_run(run, state)
                artifacts.append(run)
            if validate_artifacts:
                validate_artifacts(states, artifacts)
        return {"ok": True, "revisions": len(revisions), "runs": len(runs)}
