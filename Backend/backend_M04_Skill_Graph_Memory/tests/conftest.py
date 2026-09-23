"""Shared fixtures for M04 tests.

Every test runs **offline and against an in-memory database**. Offline is a
property rather than a convenience: the only model call in this module is the
nightly distiller, which is on no read path, so a suite that needed a key would
be a suite nobody else can run.

One wrinkle worth naming. `TestClient(app)` runs the real lifespan, and the
lifespan opens its own session to project the ontology into tables — it cannot
see FastAPI's `dependency_overrides`, which only apply to request handlers. So
`DATABASE_URL` is pointed at a throwaway file before `ai_core` is imported at
all, and the request path still gets the in-memory engine. Without that,
running the tests would quietly rewrite the developer's `dev.db`.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="m04-tests-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_TMP / 'lifespan.db').as_posix()}"
os.environ.pop("M04_SERVICE_SECRET", None)

from ai_core.db import get_session  # noqa: E402
from ai_core.evidence import EvidenceRef, EvidenceSpan, sha256_hex  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlmodel import Session, SQLModel, create_engine  # noqa: E402

from backend_M04_Skill_Graph_Memory import ontology as ontology_module  # noqa: E402
from backend_M04_Skill_Graph_Memory.models import (  # noqa: E402
    Artifact,
    ConsentRecord,
    Purpose,
)
from backend_M04_Skill_Graph_Memory.service import sync_ontology  # noqa: E402
from backend_M04_Skill_Graph_Memory.store import ObservationIn  # noqa: E402

NOW = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)


@pytest.fixture(name="graph")
def graph_fixture():
    """The real ontology, not a fixture graph.

    Deliberate: the prerequisite edges are the thing under test in half of
    these files, and a hand-built four-node graph would let a broken walk pass
    while the shipped 120-concept one deadlocks or loops.
    """
    ontology_module.reset_cache()
    return ontology_module.load()


@pytest.fixture(name="engine")
def engine_fixture():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture(name="session")
def session_fixture(engine, graph) -> Iterator[Session]:
    with Session(engine) as session:
        sync_ontology(session, graph)
        yield session


@pytest.fixture(name="client")
def client_fixture(session: Session) -> Iterator[TestClient]:
    from backend_M04_Skill_Graph_Memory.app import app

    app.dependency_overrides[get_session] = lambda: session
    # As an administrator, on purpose — as M02's suite does. These tests are
    # about beliefs, evidence and memory; the refusals have their own tests,
    # which send real student principals, and putting authorisation into every
    # test is how the first one to get it slightly wrong "fixes" it by
    # weakening the check.
    with TestClient(app, headers={"X-Role": "admin", "X-Candidate-Id": "test-admin"}) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture(name="candidate_id")
def candidate_fixture() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture(name="consent")
def consent_fixture(session: Session, candidate_id: uuid.UUID) -> ConsentRecord:
    record = ConsentRecord(
        candidate_id=candidate_id, purpose=Purpose.practice, granted_at=NOW - timedelta(days=30)
    )
    session.add(record)
    session.commit()
    return record


# ─────────────────────────────────────────────────────────────
#  BUILDERS
# ─────────────────────────────────────────────────────────────


def make_artifact(
    session: Session,
    candidate_id: uuid.UUID,
    text: str = "I would add an index on user_id so the join stops scanning.",
    *,
    session_id: uuid.UUID | None = None,
    tombstoned: bool = False,
) -> Artifact:
    artifact = Artifact(
        candidate_id=candidate_id,
        session_id=session_id or uuid.uuid4(),
        turn_id=uuid.uuid4(),
        artifact_type="transcript",
        content="" if tombstoned else text,
        checksum=sha256_hex(text),
        tombstoned_at=NOW if tombstoned else None,
        tombstone_reason="retention" if tombstoned else None,
    )
    session.add(artifact)
    session.commit()
    return artifact


def evidence_for(artifact: Artifact, quote: str | None = None) -> EvidenceRef:
    """A span ref that actually resolves against the artifact it names."""
    text = artifact.content
    quote = quote or (text[:20] if text else "x")
    start = text.find(quote)
    return EvidenceRef(
        kind="span",
        session_id=artifact.session_id,
        turn_id=artifact.turn_id,
        span=EvidenceSpan(
            artifact_type="transcript",
            artifact_id=artifact.id,
            start=max(0, start),
            end=max(0, start) + len(quote),
            quote=quote,
        ),
        checksum=artifact.checksum,
    )


def scored(
    candidate_id: uuid.UUID,
    concept_id: str,
    consent: ConsentRecord,
    evidence: list[EvidenceRef],
    *,
    correct: bool = True,
    session_id: uuid.UUID | None = None,
    turn_id: uuid.UUID | None = None,
    a: float = 1.2,
    b: float = 0.0,
    observed_at: datetime | None = None,
    **kwargs,
) -> ObservationIn:
    """A 2PL-scored answer: the simplest thing that moves theta."""
    return ObservationIn(
        candidate_id=candidate_id,
        concept_id=concept_id,
        session_id=session_id or uuid.uuid4(),
        turn_id=turn_id or uuid.uuid4(),
        evidence=evidence,
        kind="answer_scored",
        response_model="2pl",
        outcome=1.0 if correct else 0.0,
        item={"question_id": str(uuid.uuid4()), "irt_model": "2pl", "a": a, "b": b},
        consent_id=consent.id,
        observed_at=observed_at or NOW,
        **kwargs,
    )
