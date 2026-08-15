"""M04 — API surface.

Spec: §7. Two access levels, and the difference is enforced rather than
documented:

    public   the ontology. It is the same for everybody and four modules need
             it on their own hot paths.
    service  another module calling with no student present. Shared secret.
    self     a student's own beliefs, evidence and memory.

**`FailureSignature` is reachable from no endpoint here.** Not filtered out —
absent. AC-4.10 is a gate, and the cheapest way to keep a gate is to have
nothing to leak: there is no route that returns one, and a test asserts that
no route path contains the word.
"""

from __future__ import annotations

import uuid

from ai_core.modules_meta import module_status
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session

from ai_core.db import get_session

from . import service, store
from .keys import secret_matches, service_secret
from .models import RecordResult
from .ontology import UnknownConcept, load
from .store import ContendedMastery, NoConsent, ObservationIn, UnresolvableEvidence

router = APIRouter()


# ─────────────────────────────────────────────────────────────
#  ACCESS
# ─────────────────────────────────────────────────────────────


def require_service(x_service_secret: str | None = Header(default=None)) -> None:
    """One dependency, used by every `service` endpoint, and tested."""
    if not secret_matches(x_service_secret):
        raise HTTPException(status_code=401, detail="service credentials required")


def require_self(
    candidate_id: uuid.UUID,
    x_candidate_id: str | None = Header(default=None),
    x_service_secret: str | None = Header(default=None),
) -> uuid.UUID:
    """A student may read their own record; a service may read on their behalf.

    Phase 1 has no identity provider, so this is the seam where one lands: the
    header is a placeholder for a verified subject claim, and every route that
    touches a candidate's data goes through this function rather than reading
    the path parameter directly. When real auth arrives it replaces the body of
    this function and nothing else.
    """
    if service_secret() is not None and secret_matches(x_service_secret):
        return candidate_id
    if x_candidate_id and x_candidate_id != str(candidate_id):
        raise HTTPException(status_code=403, detail="not your record")
    if service_secret() is not None and not x_candidate_id:
        raise HTTPException(status_code=401, detail="identify yourself")
    return candidate_id


# ─────────────────────────────────────────────────────────────
#  META
# ─────────────────────────────────────────────────────────────


@router.get("/v1/deps", tags=["meta"])
def dependencies() -> dict:
    """M04 depends on no module, and that is worth saying out loud.

    Every other module's `/v1/deps` lists what it degrades without. This one is
    the root of the graph: eighteen modules read it and it reads none of them,
    which is exactly what lets it be built and demoed in Phase 1 before M05 or
    M13 exist.
    """
    return {
        "module": "M04",
        "dependencies": [],
        "degraded": [],
        "note": "M04 is a root: it is read by eighteen modules and reads none of them.",
    }


@router.get("/status", tags=["meta"])
def status() -> dict:
    graph = load()
    meta = module_status("M04").model_dump()
    meta["ontology"] = {
        "version": graph.version,
        "concepts": len(graph.concepts),
        "edges": len(graph.edges),
        # Never implied. AC-4.9 gates Phase-1 exit on a faculty walk of the
        # prerequisite edges, and a graph that has not had one should say so
        # everywhere it is served.
        "faculty_reviewed": graph.reviewed,
    }
    return meta


# ─────────────────────────────────────────────────────────────
#  ONTOLOGY  (public)
# ─────────────────────────────────────────────────────────────


@router.get("/v1/concepts", tags=["ontology"])
def list_concepts(domain: str | None = Query(default=None)) -> dict:
    graph = load()
    return {
        "ontology_version": graph.version,
        "faculty_reviewed": graph.reviewed,
        "count": len(graph.concepts),
        "concepts": [c.model_dump() for c in graph.by_domain(domain)],
    }


@router.get("/v1/concepts/{concept_id}", tags=["ontology"])
def get_concept(concept_id: str) -> dict:
    graph = load()
    try:
        concept = graph.get(concept_id)
    except UnknownConcept as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        **concept.model_dump(),
        "prerequisites": [n.__dict__ for n in graph.walk_up(concept_id, max_hops=1)],
        "unlocks": [n.__dict__ for n in graph.walk_down(concept_id, max_hops=1)],
    }


class ResolveRequest(BaseModel):
    labels: list[str] = Field(min_length=1)


@router.post("/v1/concepts/resolve", tags=["ontology"])
def resolve(payload: ResolveRequest, session: Session = Depends(get_session)) -> dict:
    """FR-4.21. Four modules call this; none of them can invent it.

    A label this cannot match comes back `null`. That is a real answer and the
    caller must render it as one — never as a mastery of zero (EC-4.18).
    """
    graph = load()
    resolved = service.resolve_labels(session, payload.labels, graph)
    return {
        "resolved": resolved,
        "unresolved": sorted(label for label, cid in resolved.items() if cid is None),
        "ontology_version": graph.version,
    }


# ─────────────────────────────────────────────────────────────
#  BELIEFS  (service + self)
# ─────────────────────────────────────────────────────────────


@router.get("/v1/skill-graph/theta", tags=["mastery"], dependencies=[Depends(require_service)])
def skill_graph_theta(
    candidate: uuid.UUID,
    concepts: str = Query(default="", description="comma-separated topic labels or concept ids"),
    session: Session = Depends(get_session),
) -> dict:
    """The path M15 already calls. Adopted rather than replaced (§7)."""
    labels = [part.strip() for part in concepts.split(",") if part.strip()]
    return service.theta_by_label(session, candidate, labels)


@router.get("/v1/candidates/{candidate_id}/mastery", tags=["mastery"])
def mastery(
    candidate_id: uuid.UUID = Depends(require_self),
    domain: str | None = Query(default=None),
    state: str | None = Query(default=None),
    session: Session = Depends(get_session),
) -> dict:
    graph = load()
    rows = service.mastery_for(session, candidate_id, domain=domain)
    if state:
        rows = [r for r in rows if r.state == state]

    measured = {r.concept_id for r in rows}
    untested = [
        c.name for c in graph.by_domain(domain) if c.id not in measured
    ]
    return {
        "ontology_version": graph.version,
        "measured": [r.model_dump() for r in rows],
        # The count and the names, NOT 108 empty rows. An empty grid teaches a
        # student the product is broken (§2.3, EC-4.1).
        "not_yet_tested": {"count": len(untested), "names": untested},
        "totals": {"measured": len(rows), "in_ontology": len(graph.by_domain(domain))},
    }


@router.get("/v1/candidates/{candidate_id}/mastery/{concept_id}/evidence", tags=["mastery"])
def evidence(
    concept_id: str,
    candidate_id: uuid.UUID = Depends(require_self),
    session: Session = Depends(get_session),
) -> dict:
    """"Why is this value what it is?" — Rule 3's escape hatch (FR-4.12)."""
    return {
        "concept_id": concept_id,
        "bkt_p_known": service.bkt_for(session, candidate_id, concept_id),
        "observations": service.evidence_for(session, candidate_id, concept_id),
    }


@router.get("/v1/candidates/{candidate_id}/bottlenecks", tags=["mastery"])
def bottlenecks(
    candidate_id: uuid.UUID = Depends(require_self),
    session: Session = Depends(get_session),
) -> dict:
    found = service.bottlenecks(session, candidate_id)
    return {
        "bottlenecks": found,
        # Said explicitly, because "no bottleneck" and "we could not work it
        # out" are different messages and the card renders neither by guessing.
        "reason": None if found else "no concept blocks two or more of your weak topics",
    }


@router.get("/v1/candidates/{candidate_id}/retests", tags=["mastery"])
def list_retests(
    candidate_id: uuid.UUID = Depends(require_self),
    session: Session = Depends(get_session),
) -> dict:
    return {"retests": service.retests(session, candidate_id)}


class DisputeRequest(BaseModel):
    reason: str = ""


@router.post("/v1/candidates/{candidate_id}/mastery/{concept_id}/dispute", tags=["mastery"])
def dispute(
    concept_id: str,
    payload: DisputeRequest,
    candidate_id: uuid.UUID = Depends(require_self),
    session: Session = Depends(get_session),
) -> dict:
    return service.open_dispute(session, candidate_id, concept_id, payload.reason)


# ─────────────────────────────────────────────────────────────
#  THE WRITE PATH  (service)
# ─────────────────────────────────────────────────────────────


class ObservationBatch(BaseModel):
    observations: list[ObservationIn] = Field(min_length=1)


@router.post(
    "/v1/candidates/{candidate_id}/observations",
    tags=["write"],
    dependencies=[Depends(require_service)],
)
def post_observations(
    candidate_id: uuid.UUID,
    payload: ObservationBatch,
    session: Session = Depends(get_session),
) -> list[RecordResult]:
    """A LIST, in one transaction (§6.2).

    M13 emits several observations per turn, and the 60 ms budget in §11 is per
    call rather than per observation. Every error here is a 4xx with a reason a
    caller can act on: silently accepting an observation we could not honour
    would leave the producer believing a number moved when it did not.
    """
    for obs in payload.observations:
        if obs.candidate_id != candidate_id:
            raise HTTPException(
                status_code=400,
                detail="observation candidate_id does not match the path",
            )
    try:
        return store.record_batch(session, payload.observations)
    except UnknownConcept as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except NoConsent as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except UnresolvableEvidence as exc:
        raise HTTPException(
            status_code=422, detail=f"evidence does not resolve: {exc}"
        ) from exc
    except ContendedMastery as exc:
        # 409, and the caller replays. The uuid5 id makes that safe, which is
        # why this is a retry rather than a lost update (EC-4.15).
        raise HTTPException(status_code=409, detail=str(exc)) from exc
