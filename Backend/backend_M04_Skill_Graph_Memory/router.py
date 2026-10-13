"""M04 — API surface.

Spec: §7. Access is enforced rather than documented, in two independent
checks:

    who      every route whose path names a candidate asks `ai_core.identity`
             whether the caller may see that student — `candidate_guard`, on
             the ROUTER, so a route added later is covered without a line.
             Anonymous is refused, including on a dev machine.
    which    `service` routes also require the shared secret: they are called
             by another module, and the secret is how M04 knows it is one.

A module calling on a student's behalf sends both — the secret, and the
student it is acting for (`ai_core.guard.identity_headers`). Until 2026-09-23
the secret alone let a module read ANY student's record, and with no secret
configured (the dev default) an anonymous caller could too: `require_self`
failed open. The platform's rule is that there is no service role — a module
carries a student's request, it does not make its own — so the secret now
says *which caller*, and never *whose data*.

    public   the ontology. It is the same for everybody and four modules need
             it on their own hot paths. Names no candidate, so not gated.

**`FailureSignature` is reachable from no endpoint here.** Not filtered out —
absent. AC-4.10 is a gate, and the cheapest way to keep a gate is to have
nothing to leak: there is no route that returns one, and a test asserts that
no route path contains the word.
"""

from __future__ import annotations

import uuid
from datetime import date as date_type
from datetime import datetime

from ai_core.db import get_session
from ai_core.guard import candidate_guard
from ai_core.modules_meta import module_status
from ai_core.service import require_service
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlmodel import Session

from . import service, store
from .curricula import coursework as coursework_for
from .curricula import load_curricula
from .models import RecordResult
from .ontology import UnknownConcept, load
from .store import ContendedMastery, NoConsent, ObservationIn, UnresolvableEvidence

router = APIRouter(dependencies=[Depends(candidate_guard())])


# ─────────────────────────────────────────────────────────────
#  ACCESS
# ─────────────────────────────────────────────────────────────


#: Every `service` endpoint takes this one dependency — Platform_Core's since
#: v0.12.0 (`ai_core.service`), which M06, M13 and M15 send from the same place.


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
    # Named, so a screen can say "it builds on Functions" without a second
    # lookup per neighbour — or, worse, showing the id.
    def named(n) -> dict:
        return {**n.__dict__, "name": graph.get(n.concept_id).name}

    return {
        **concept.model_dump(),
        "prerequisites": [named(n) for n in graph.walk_up(concept_id, max_hops=1)],
        "unlocks": [named(n) for n in graph.walk_down(concept_id, max_hops=1)],
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
#  CURRICULA  (public) — what the sign-in step offers
# ─────────────────────────────────────────────────────────────


@router.get("/v1/curricula", tags=["curricula"])
def list_curricula() -> list[dict]:
    """The programmes a student can pick at sign-in, built from the college's
    own curriculum PDFs (`jobs/curricula.py`)."""
    return [c.summary() for c in load_curricula().values()]


@router.get("/v1/curricula/{curriculum_id}", tags=["curricula"])
def get_curriculum(curriculum_id: str) -> dict:
    """Every semester's courses and elective slots, the elective baskets, and
    for each course the concepts its syllabus teaches, named, with the
    syllabus words that matched."""
    curriculum = load_curricula().get(curriculum_id)
    if curriculum is None:
        raise HTTPException(status_code=404, detail=f"no curriculum {curriculum_id!r}")
    return curriculum.document


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
    candidate_id: uuid.UUID,
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
    candidate_id: uuid.UUID,
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
    candidate_id: uuid.UUID,
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
    candidate_id: uuid.UUID,
    session: Session = Depends(get_session),
) -> dict:
    return {"retests": service.retests(session, candidate_id)}


class DisputeRequest(BaseModel):
    reason: str = ""


@router.post("/v1/candidates/{candidate_id}/mastery/{concept_id}/dispute", tags=["mastery"])
def dispute(
    concept_id: str,
    payload: DisputeRequest,
    candidate_id: uuid.UUID,
    session: Session = Depends(get_session),
) -> dict:
    return service.open_dispute(session, candidate_id, concept_id, payload.reason)


@router.get("/v1/candidates/{candidate_id}/trajectory", tags=["mastery"])
def trajectory(
    candidate_id: uuid.UUID,
    concept: str | None = Query(default=None, description="one concept id; omit for all"),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    session: Session = Depends(get_session),
) -> dict:
    """§7 · §8 — the contract M19 needs. M19 owns the chart; M04 owns the data.

    Served from the `theta_after` / `se_after` stored on each observation, so
    history stays drawn on the scale it was scored on rather than being
    recomputed under whatever estimator is current.
    """
    return service.trajectory(
        session, candidate_id, concept_id=concept, since=since, until=until
    )


# ─────────────────────────────────────────────────────────────
#  THE WORKING TIER  (service) — what an agent gets at session start
# ─────────────────────────────────────────────────────────────


@router.get(
    "/v1/candidates/{candidate_id}/profile-summary",
    tags=["memory"],
    dependencies=[Depends(require_service)],
)
def profile_summary(
    candidate_id: uuid.UUID,
    session_id: uuid.UUID = Query(description="the session this context is pinned to"),
    session: Session = Depends(get_session),
) -> dict:
    """FR-4.23 — pinned, byte-identical for the life of a session (AC-4.13).

    `session_id` is required rather than optional. An unpinned summary is a
    different object with a different guarantee, and letting one endpoint
    return either depending on a query parameter is how a caller ends up
    believing it has a stable context when it does not.
    """
    try:
        return service.pinned_profile_summary(session, candidate_id, session_id)
    except service.SessionCandidateMismatch as exc:
        raise HTTPException(
            status_code=409, detail="session belongs to another candidate"
        ) from exc


# ─────────────────────────────────────────────────────────────
#  THE STUDENT'S RIGHTS  (FR-4.18a/b/c)
# ─────────────────────────────────────────────────────────────


class ConsentOut(BaseModel):
    """What a module cites on every observation it writes."""

    consent_id: uuid.UUID
    candidate_id: uuid.UUID
    purpose: str
    policy_version: str
    granted_at: datetime
    revoked_at: datetime | None = None
    active: bool


class GrantConsent(BaseModel):
    purpose: str = Field(
        default="practice",
        description="practice · institutional_reporting · research (FR-4.18c)",
    )
    policy_version: str = Field(default="1.0")


def _consent_out(record) -> ConsentOut:
    return ConsentOut(
        consent_id=record.id,
        candidate_id=record.candidate_id,
        purpose=record.purpose,
        policy_version=record.policy_version,
        granted_at=record.granted_at,
        revoked_at=record.revoked_at,
        active=record.active,
    )


@router.get("/v1/candidates/{candidate_id}/consent", tags=["rights"])
def read_consent(
    candidate_id: uuid.UUID,
    purpose: str | None = Query(
        default=None, description="omit to list every consent on record"
    ),
    session: Session = Depends(get_session),
) -> list[ConsentOut]:
    """What this student has agreed to — FR-4.20, from the other side.

    The table has existed since day one and every write is checked against it
    (`store.consent_active`), but nothing could read it: M06 resolves consent
    at session start and had no route to ask, so it reported "not recorded" on
    every session and M13 emitted no observations at all. A rule nobody can
    query is a rule that silently answers no.
    """
    if purpose is not None:
        found = service.active_consent(session, candidate_id, purpose)
        return [_consent_out(found)] if found is not None else []
    return [_consent_out(r) for r in service.consents_for(session, candidate_id)]


@router.post("/v1/candidates/{candidate_id}/consent", tags=["rights"], status_code=201)
def grant_consent(
    body: GrantConsent,
    response: Response,
    candidate_id: uuid.UUID,
    session: Session = Depends(get_session),
) -> ConsentOut:
    """Record consent for one purpose. 201 when it is new, 200 when it stood.

    Idempotent: a student starting a second interview has not consented twice.
    A grant at a new `policy_version` is a genuine second consent, because the
    thing being agreed to changed — the old row stays, unrevoked, as the
    record of what was true then.
    """
    try:
        record, created = service.grant_consent(
            session, candidate_id, body.purpose, policy_version=body.policy_version
        )
    except service.UnknownPurpose as exc:
        raise HTTPException(
            status_code=400,
            detail=f"unknown purpose '{body.purpose}' — "
            "practice, institutional_reporting or research",
        ) from exc
    if not created:
        response.status_code = 200
    return _consent_out(record)


class DriveIn(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    #: ISO date. A drive without a date is a company, not a countdown.
    date: date_type
    company_id: uuid.UUID | None = None
    #: M15's drive variant, when the student picked one — what lets "practise
    #: for this drive" plan from that drive's requirement set.
    drive_id: uuid.UUID | None = None


class CompanyIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    company_id: uuid.UUID | None = None


class ProfileIn(BaseModel):
    """Every field optional: settings saves one at a time, the welcome step
    saves them together. A field left out is kept, not cleared."""

    display_name: str | None = Field(default=None, max_length=60)
    target_role: str | None = Field(default=None, max_length=80)
    companies: list[CompanyIn] | None = Field(default=None, max_length=10)
    drives: list[DriveIn] | None = Field(default=None, max_length=10)
    year: str | None = Field(default=None, max_length=20)
    branch: str | None = Field(default=None, max_length=60)
    #: An id from `/v1/curricula`, or "" for a programme without one.
    curriculum_id: str | None = Field(default=None, max_length=80)
    semester: int | None = Field(default=None, ge=1, le=8)
    #: Codes from that curriculum: this semester's courses and chosen electives.
    courses: list[str] | None = Field(default=None, max_length=24)
    weekly_goal: int | None = Field(default=None, ge=1, le=7)
    reminder_time: str | None = Field(default=None, pattern=r"^$|^([01]\d|2[0-3]):[0-5]\d$")
    #: True from the welcome step: stamps `onboarded_at` the first time.
    onboarded: bool = False


class ProfileOut(BaseModel):
    candidate_id: uuid.UUID
    display_name: str
    target_role: str
    companies: list[dict]
    drives: list[dict]
    year: str
    branch: str
    curriculum_id: str
    semester: int | None
    courses: list[str]
    weekly_goal: int
    reminder_time: str
    onboarded_at: datetime | None
    updated_at: datetime


def _profile_out(row) -> ProfileOut:
    return ProfileOut(**row.model_dump())


@router.get("/v1/candidates/{candidate_id}/profile", tags=["rights"], response_model=ProfileOut)
def read_profile(candidate_id: uuid.UUID, session: Session = Depends(get_session)) -> ProfileOut:
    """What the student said they are preparing for. Empty, not 404, before
    they have said anything."""
    return _profile_out(service.read_profile(session, candidate_id))


@router.put("/v1/candidates/{candidate_id}/profile", tags=["rights"], response_model=ProfileOut)
def write_profile(
    body: ProfileIn, candidate_id: uuid.UUID, session: Session = Depends(get_session)
) -> ProfileOut:
    fields = body.model_dump(exclude_unset=True, exclude={"onboarded"}, mode="json")
    # `semester: null` is an answer ("graduated", or "I'd rather not say"),
    # unlike every other field, where null means "not part of this save".
    clear_semester = "semester" in fields and fields["semester"] is None
    fields = {k: v for k, v in fields.items() if v is not None}
    if clear_semester:
        fields["semester"] = None
    if "drives" in fields:
        # Soonest first, so "your next drive" is the first row everywhere.
        fields["drives"] = sorted(fields["drives"], key=lambda d: d["date"])
    if "curriculum_id" in fields or "courses" in fields:
        _check_courses(session, candidate_id, fields)
    return _profile_out(
        service.write_profile(session, candidate_id, fields, onboarded=body.onboarded)
    )


@router.get("/v1/candidates/{candidate_id}/coursework", tags=["curricula"])
def read_coursework(candidate_id: uuid.UUID, session: Session = Depends(get_session)) -> dict:
    """The concepts the student's courses have taught so far: this semester's
    ticked courses, then every earlier semester's (`curricula.coursework`).
    M06 plans a mixed interview from it (2026-10-13). Empty, never 404, for a
    student who has not said their programme or semester."""
    profile = service.read_profile(session, candidate_id)
    curriculum = load_curricula().get(profile.curriculum_id) if profile.curriculum_id else None
    return coursework_for(curriculum, profile.semester, profile.year, list(profile.courses or []))


def _check_courses(session: Session, candidate_id: uuid.UUID, fields: dict) -> None:
    """A course code is an exact value a planner will act on, so it is
    checked against the curriculum, never trusted (422 names what is wrong).
    Changing programme without naming courses clears them: the old codes
    belong to the other curriculum."""
    current = service.read_profile(session, candidate_id)
    curriculum_id = fields.get("curriculum_id", current.curriculum_id)
    curricula = load_curricula()
    if curriculum_id and curriculum_id not in curricula:
        raise HTTPException(status_code=422, detail=f"no curriculum {curriculum_id!r}")
    if "courses" not in fields:
        if curriculum_id != current.curriculum_id:
            fields["courses"] = []
        return
    courses = list(dict.fromkeys(fields["courses"]))  # one of each, order kept
    if courses and not curriculum_id:
        raise HTTPException(status_code=422, detail="courses need a curriculum_id")
    unknown = [c for c in courses if curriculum_id and c not in curricula[curriculum_id].courses]
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"not in {curriculum_id}: {', '.join(unknown)}",
        )
    fields["courses"] = courses


@router.get("/v1/candidates/{candidate_id}/export", tags=["rights"])
def export_memory(
    candidate_id: uuid.UUID,
    session: Session = Depends(get_session),
) -> dict:
    """FR-4.18a — every row, not a summary of them."""
    return service.export_memory(session, candidate_id)


@router.delete("/v1/candidates/{candidate_id}/memory", tags=["rights"])
def delete_memory(
    candidate_id: uuid.UUID,
    purpose: str | None = Query(
        default=None,
        description="omit for a full hard delete (FR-4.18b); "
        "'research' or 'institutional_reporting' to revoke one purpose (FR-4.18c)",
    ),
    session: Session = Depends(get_session),
) -> dict:
    """Two operations behind one path, and the difference is stated, not implied.

    Without `purpose` this is a hard delete: rows go, and the numbers cannot
    come back, because the episodic tier they were re-derivable from is gone
    too. With `purpose` it is a revocation of that purpose alone — a student
    withdrawing from the study keeps their practice history.
    """
    if purpose is None:
        return service.delete_memory(session, candidate_id)
    try:
        return service.revoke_purpose(session, candidate_id, purpose)
    except service.CannotRevokePractice as exc:
        raise HTTPException(
            status_code=400,
            detail="revoking 'practice' is a full delete — call this without ?purpose",
        ) from exc


# ─────────────────────────────────────────────────────────────
#  THE WRITE PATH  (service)
# ─────────────────────────────────────────────────────────────


class ArtifactIn(BaseModel):
    """The text a quote will be quoted from — §5.1's episodic tier."""

    candidate_id: uuid.UUID
    session_id: uuid.UUID
    turn_id: uuid.UUID | None = None
    artifact_type: str = Field(default="transcript")
    content: str = Field(min_length=1)


class ArtifactOut(BaseModel):
    artifact_id: uuid.UUID
    checksum: str
    created: bool


@router.post(
    "/v1/candidates/{candidate_id}/artifacts",
    tags=["write"],
    dependencies=[Depends(require_service)],
    status_code=201,
)
def post_artifact(
    candidate_id: uuid.UUID,
    payload: ArtifactIn,
    response: Response,
    session: Session = Depends(get_session),
) -> ArtifactOut:
    """Register an answer, a submission or a canvas before anything cites it.

    `m04_artifacts` has been the resolver's whole world since day one and
    nothing could write to it, so every evidence ref another module sent
    resolved to `absent` and the observation behind it was refused with
    "evidence does not resolve". A scored interview reached M04 and moved
    nothing — the failure was at this seam, not in the scoring.

    The id is derived from `(turn_id or session_id, artifact_type)`, so the
    producer never has to remember one and a retry is a no-op: 201 the first
    time, 200 afterwards. The content is immutable, because evidence quotes
    character offsets into it.
    """
    if payload.candidate_id != candidate_id:
        raise HTTPException(
            status_code=400, detail="artifact candidate_id does not match the path"
        )
    artifact, created = service.register_artifact(
        session,
        candidate_id=candidate_id,
        session_id=payload.session_id,
        turn_id=payload.turn_id,
        content=payload.content,
        artifact_type=payload.artifact_type,
    )
    if not created:
        response.status_code = 200
    return ArtifactOut(artifact_id=artifact.id, checksum=artifact.checksum, created=created)


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
