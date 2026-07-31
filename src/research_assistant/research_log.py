from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from research_assistant.artifacts import utc_now
from research_assistant.errors import ResearchAssistantError


class ResearchLogError(ResearchAssistantError):
    pass


HypothesisStatus = Literal[
    "draft", "active", "supported", "refuted", "inconclusive", "archived"
]


class HypothesisInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=240)
    statement: str = Field(min_length=1)
    expected_outcome: str | None = None
    decision_criteria: str | None = None
    status: HypothesisStatus = "draft"
    tags: list[str] = Field(default_factory=list)
    parent_id: str | None = None


class EvidenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hypothesis_id: str
    kind: Literal["run", "report", "selection", "publication", "dataset", "note"]
    reference: str = Field(min_length=1)
    summary: str | None = None
    supports: Literal["support", "contradict", "neutral"] = "neutral"
    metadata: dict[str, Any] = Field(default_factory=dict)


class DecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=240)
    choice: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    alternatives: list[str] = Field(default_factory=list)
    next_action: str | None = None
    hypothesis_id: str | None = None
    references: list[str] = Field(default_factory=list)
    status: Literal["proposed", "accepted", "reversed", "superseded"] = "accepted"


class ResearchLog:
    """Audit-friendly hypothesis, evidence and decision journal."""

    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).expanduser().resolve()
        self.database = self.workspace / ".ra" / "research.sqlite3"
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.database)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self._schema()

    def close(self) -> None:
        self.connection.close()

    def _schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS hypotheses (
                hypothesis_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                statement TEXT NOT NULL,
                expected_outcome TEXT,
                decision_criteria TEXT,
                status TEXT NOT NULL,
                tags_json TEXT NOT NULL,
                parent_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                conclusion TEXT,
                FOREIGN KEY(parent_id) REFERENCES hypotheses(hypothesis_id)
            );
            CREATE TABLE IF NOT EXISTS evidence (
                evidence_id TEXT PRIMARY KEY,
                hypothesis_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                reference TEXT NOT NULL,
                summary TEXT,
                supports TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(hypothesis_id) REFERENCES hypotheses(hypothesis_id)
            );
            CREATE TABLE IF NOT EXISTS decisions (
                decision_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                choice TEXT NOT NULL,
                rationale TEXT NOT NULL,
                alternatives_json TEXT NOT NULL,
                next_action TEXT,
                hypothesis_id TEXT,
                references_json TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(hypothesis_id) REFERENCES hypotheses(hypothesis_id)
            );
            CREATE INDEX IF NOT EXISTS evidence_hypothesis_idx
                ON evidence(hypothesis_id, created_at);
            CREATE INDEX IF NOT EXISTS decisions_hypothesis_idx
                ON decisions(hypothesis_id, created_at);
            """
        )
        self.connection.commit()

    def create_hypothesis(self, payload: HypothesisInput) -> dict[str, Any]:
        if payload.parent_id and self.get_hypothesis(payload.parent_id) is None:
            raise ResearchLogError(f"parent hypothesis does not exist: {payload.parent_id}")
        identifier = f"hyp-{uuid4().hex[:12]}"
        now = utc_now()
        self.connection.execute(
            """
            INSERT INTO hypotheses(
                hypothesis_id, title, statement, expected_outcome, decision_criteria,
                status, tags_json, parent_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                identifier,
                payload.title,
                payload.statement,
                payload.expected_outcome,
                payload.decision_criteria,
                payload.status,
                json.dumps(list(dict.fromkeys(payload.tags))),
                payload.parent_id,
                now,
                now,
            ),
        )
        self.connection.commit()
        return self.require_hypothesis(identifier)

    def _hypothesis_row(self, row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["tags"] = json.loads(value.pop("tags_json") or "[]")
        value["evidence"] = [
            self._evidence_row(item)
            for item in self.connection.execute(
                "SELECT * FROM evidence WHERE hypothesis_id = ? ORDER BY created_at",
                (value["hypothesis_id"],),
            ).fetchall()
        ]
        value["decisions"] = [
            self._decision_row(item)
            for item in self.connection.execute(
                "SELECT * FROM decisions WHERE hypothesis_id = ? ORDER BY created_at",
                (value["hypothesis_id"],),
            ).fetchall()
        ]
        return value

    @staticmethod
    def _evidence_row(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["metadata"] = json.loads(value.pop("metadata_json") or "{}")
        return value

    @staticmethod
    def _decision_row(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["alternatives"] = json.loads(value.pop("alternatives_json") or "[]")
        value["references"] = json.loads(value.pop("references_json") or "[]")
        return value

    def get_hypothesis(self, hypothesis_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM hypotheses WHERE hypothesis_id = ?", (hypothesis_id,)
        ).fetchone()
        return self._hypothesis_row(row) if row else None

    def require_hypothesis(self, hypothesis_id: str) -> dict[str, Any]:
        value = self.get_hypothesis(hypothesis_id)
        if value is None:
            raise ResearchLogError(f"hypothesis does not exist: {hypothesis_id}")
        return value

    def list_hypotheses(
        self,
        *,
        status: HypothesisStatus | None = None,
        search: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        clauses = ["1=1"]
        parameters: list[Any] = []
        if status:
            clauses.append("status = ?")
            parameters.append(status)
        if search:
            clauses.append("(title LIKE ? OR statement LIKE ? OR tags_json LIKE ?)")
            needle = f"%{search}%"
            parameters.extend([needle, needle, needle])
        parameters.append(max(1, min(limit, 10000)))
        rows = self.connection.execute(
            f"""
            SELECT * FROM hypotheses WHERE {' AND '.join(clauses)}
            ORDER BY updated_at DESC LIMIT ?
            """,
            parameters,
        ).fetchall()
        return [self._hypothesis_row(row) for row in rows]

    def update_hypothesis(
        self,
        hypothesis_id: str,
        *,
        status: HypothesisStatus | None = None,
        conclusion: str | None = None,
        title: str | None = None,
        statement: str | None = None,
    ) -> dict[str, Any]:
        current = self.require_hypothesis(hypothesis_id)
        self.connection.execute(
            """
            UPDATE hypotheses SET title = ?, statement = ?, status = ?, conclusion = ?,
                                  updated_at = ?
            WHERE hypothesis_id = ?
            """,
            (
                title or current["title"],
                statement or current["statement"],
                status or current["status"],
                conclusion if conclusion is not None else current.get("conclusion"),
                utc_now(),
                hypothesis_id,
            ),
        )
        self.connection.commit()
        return self.require_hypothesis(hypothesis_id)

    def add_evidence(self, payload: EvidenceInput) -> dict[str, Any]:
        self.require_hypothesis(payload.hypothesis_id)
        identifier = f"ev-{uuid4().hex[:12]}"
        self.connection.execute(
            """
            INSERT INTO evidence(
                evidence_id, hypothesis_id, kind, reference, summary,
                supports, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                identifier,
                payload.hypothesis_id,
                payload.kind,
                payload.reference,
                payload.summary,
                payload.supports,
                json.dumps(payload.metadata, sort_keys=True),
                utc_now(),
            ),
        )
        self.connection.execute(
            "UPDATE hypotheses SET updated_at = ? WHERE hypothesis_id = ?",
            (utc_now(), payload.hypothesis_id),
        )
        self.connection.commit()
        row = self.connection.execute(
            "SELECT * FROM evidence WHERE evidence_id = ?", (identifier,)
        ).fetchone()
        assert row is not None
        return self._evidence_row(row)

    def record_decision(self, payload: DecisionInput) -> dict[str, Any]:
        if payload.hypothesis_id:
            self.require_hypothesis(payload.hypothesis_id)
        identifier = f"dec-{uuid4().hex[:12]}"
        now = utc_now()
        self.connection.execute(
            """
            INSERT INTO decisions(
                decision_id, title, choice, rationale, alternatives_json,
                next_action, hypothesis_id, references_json, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                identifier,
                payload.title,
                payload.choice,
                payload.rationale,
                json.dumps(payload.alternatives),
                payload.next_action,
                payload.hypothesis_id,
                json.dumps(payload.references),
                payload.status,
                now,
                now,
            ),
        )
        if payload.hypothesis_id:
            self.connection.execute(
                "UPDATE hypotheses SET updated_at = ? WHERE hypothesis_id = ?",
                (now, payload.hypothesis_id),
            )
        self.connection.commit()
        return self.require_decision(identifier)

    def require_decision(self, decision_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT * FROM decisions WHERE decision_id = ?", (decision_id,)
        ).fetchone()
        if row is None:
            raise ResearchLogError(f"decision does not exist: {decision_id}")
        return self._decision_row(row)

    def list_decisions(self, *, limit: int = 1000) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM decisions ORDER BY updated_at DESC LIMIT ?",
            (max(1, min(limit, 10000)),),
        ).fetchall()
        return [self._decision_row(row) for row in rows]

    def export(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "exported_at": utc_now(),
            "hypotheses": self.list_hypotheses(limit=10000),
            "decisions": self.list_decisions(limit=10000),
        }
