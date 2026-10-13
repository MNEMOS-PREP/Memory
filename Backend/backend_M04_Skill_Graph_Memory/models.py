"""M04 — Skill Graph & MNEMOS Memory · data contracts.

Spec: plan_in_depth/M04_Skill_Graph_Memory.md §5 (Data contracts), §5.4 (storage)

**One schema, two stores.** There is no raw DDL here and there is none in the
spec either, deliberately (§5.4, Trap 8). `TIMESTAMPTZ`, `JSONB`, `TEXT[]`,
`VECTOR(1024)` and `USING hnsw` are Postgres-only, and the ones SQLite
*accepts* are worse than the ones it rejects: `VECTOR(1024)` silently becomes
a text column and the first similarity search returns nonsense. The platform's
first promise is that a module clones, installs and runs on its own, so these
are SQLModel classes that work on both, and the two-store differences are one
table in the spec rather than a second schema here.

    Vectors      SQLite: float32 bytes in a BLOB, brute-force cosine in Python
                 Postgres: pgvector, same query shape
    Working tier both: a table with a `stale` flag. NOT a materialised view —
                 Postgres cannot refresh one incrementally, so "refreshed on
                 write" was never implementable.
    Graph walk   both: WITH RECURSIVE.

Every table that holds a belief carries `ontology_version`. Without it EC-4.4
(concept removed) and EC-4.5 (concept split) have nothing to migrate on.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from ai_core.timeutil import utcnow
from pydantic import BaseModel
from pydantic import Field as PydanticField
from sqlalchemy import JSON, Column, LargeBinary
from sqlmodel import Field, SQLModel

# ─────────────────────────────────────────────────────────────
#  ENUMS
# ─────────────────────────────────────────────────────────────


class ObservationKind(StrEnum):
    answer_scored = "answer_scored"
    code_submitted = "code_submitted"
    mcq_answered = "mcq_answered"
    probe_depth = "probe_depth"
    hint_used = "hint_used"
    self_reported = "self_reported"
    gd_contribution = "gd_contribution"
    drill_completed = "drill_completed"
    #: §6.4 writes real rows rather than moving a number with nothing behind
    #: it. Without this, AC-4.1 fails on M04's own write path.
    propagated = "propagated"


class ResponseModel(StrEnum):
    two_pl = "2pl"
    grm = "grm"
    three_pl = "3pl"
    #: Not theta-eligible: free-form probes, self-reports, drills, and every
    #: M05 *grounded* item. Recorded, counted, shown — but it does not move the
    #: estimate, and the drawer says so (EC-4.17).
    none = "none"


class MemoryTier(StrEnum):
    episodic = "episodic"
    semantic = "semantic"
    working = "working"


class FactKind(StrEnum):
    """A closed set, for the same reason `MemoryFact.kind` is a Literal in the
    spec: the distiller's JSON schema constrains it to an enum, so a kind the
    product never designed a rendering for is structurally impossible."""

    break_point = "break_point"
    story = "story"
    failure_signature = "failure_signature"
    comm_fingerprint = "comm_fingerprint"
    preference = "preference"


class Purpose(StrEnum):
    """FR-4.18c. Revocation is per purpose, so these must be separable at the
    row level rather than inferred later."""

    practice = "practice"
    institutional_reporting = "institutional_reporting"
    research = "research"


class RetestReason(StrEnum):
    dispute = "dispute"
    inconsistent = "inconsistent"
    decay = "decay"
    propagated_unverified = "propagated_unverified"
    counselor = "counselor"


# ─────────────────────────────────────────────────────────────
#  VALUE OBJECTS  (not tables — they travel on observations)
# ─────────────────────────────────────────────────────────────


class ItemParams(BaseModel):
    """The item AS ADMINISTERED.

    Copied onto the observation, never referenced: M05 recalibrates nightly,
    and theta must stay reproducible from what was true at the time. A foreign
    key here would mean last night's recalibration silently rewrote the
    evidence behind a number a student was shown in March.
    """

    question_id: uuid.UUID
    irt_model: ResponseModel
    #: Discrimination. Required by §6.3's likelihood — an observation that
    #: cannot supply it is not theta-eligible, rather than being scored against
    #: a hardcoded constant that would silently define the whole ability scale.
    a: float
    #: Difficulty, or GRM category thresholds.
    b: float | list[float]
    #: 3PL guessing, MCQ only.
    c: float | None = None
    #: Parameter uncertainty. Where known, it ATTENUATES the update rather than
    #: being ignored: a_eff = a / sqrt(1 + a^2 * se_b^2).
    se_b: float | None = None
    params_source: str = "prior"
    bank_version: str = "1.0"


# ─────────────────────────────────────────────────────────────
#  ONTOLOGY  (projected from YAML so SQL can join against it)
# ─────────────────────────────────────────────────────────────
#
#  The YAML file is the source of truth and the in-memory graph is what the
#  write path validates against. These tables exist because §6.8's bottleneck
#  walk is a recursive CTE that has to JOIN concepts and edges, and pulling a
#  120-node graph into Python to do that in a loop would be slower and less
#  honest than the query the spec actually publishes.


class ConceptRow(SQLModel, table=True):
    __tablename__ = "m04_concepts"

    id: str = Field(primary_key=True)
    ontology_version: str = Field(primary_key=True)
    name: str
    domain: str = Field(index=True)
    level: str
    foundational_floor: bool = False
    typical_question_time_s: int = 300


class ConceptEdgeRow(SQLModel, table=True):
    __tablename__ = "m04_concept_edges"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    src: str = Field(index=True)
    dst: str = Field(index=True)
    kind: str = Field(index=True)
    strength: float = 1.0
    ontology_version: str = Field(index=True)


class ConceptAliasRow(SQLModel, table=True):
    """FR-4.21. Also queryable from SQL, because M01/M02/M15 batch-resolve
    hundreds of labels and a join beats 300 round trips."""

    __tablename__ = "m04_concept_aliases"

    alias_normalised: str = Field(primary_key=True)
    ontology_version: str = Field(primary_key=True)
    concept_id: str = Field(index=True)


# ─────────────────────────────────────────────────────────────
#  CONSENT  (FR-4.20, AC-4.11)
# ─────────────────────────────────────────────────────────────


class ConsentRecord(SQLModel, table=True):
    """No observation or fact is written without an ACTIVE one of these.

    Not in §5.4's table list, and it has to be: `Observation.consent_id` is a
    required field and FR-4.20 is a gate, so the thing it points at needs a
    home. Per purpose, because FR-4.18c revokes one purpose without touching
    the others — a student withdrawing from the study keeps their practice
    history.
    """

    __tablename__ = "m04_consent"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    candidate_id: uuid.UUID = Field(index=True)
    purpose: str = Field(index=True)
    granted_at: datetime = Field(default_factory=utcnow)
    #: Set on revocation. Rows keep their history: "when did they withdraw" is
    #: a question the ethics annexe has to be able to answer.
    revoked_at: datetime | None = None
    #: FR-4.18c gives 30 days to complete a revocation. Recorded so a sweep can
    #: find what it still owes rather than trusting a cron to have run.
    purge_due_at: datetime | None = None
    policy_version: str = "1.0"

    @property
    def active(self) -> bool:
        return self.revoked_at is None


class StudentProfile(SQLModel, table=True):
    """What the student told us they are preparing for — and nothing inferred.

    Added 2026-10-04 so that the platform can ask once and remember: a name
    for the greeting, the role and companies they are aiming at, the drives
    they have dates for, and the habits they chose (a weekly goal, a reminder
    time). Every field is the student's own answer, typed or picked; nothing
    here is a belief, so none of it carries an ontology version or evidence.

    It lives in M04 because M04 is the platform's memory of a person and
    already owns their rights: the export returns this row and the delete
    removes it, with no second module to remember.
    """

    __tablename__ = "m04_student_profile"

    candidate_id: uuid.UUID = Field(primary_key=True)
    display_name: str = ""
    target_role: str = ""
    #: Company ids from M15 where the student picked one, or a typed name.
    companies: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
    #: `[{"label": "TCS Digital", "date": "2026-10-16", "company_id": ...}]`.
    drives: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
    year: str = ""
    branch: str = ""
    #: The programme, as an id from `/v1/curricula` (2026-10-13). Empty for a
    #: branch the college has not published a curriculum for; `branch` then
    #: carries what the student typed.
    curriculum_id: str = ""
    #: 1-8. None means not said, or graduated (`year` says which).
    semester: int | None = None
    #: Course codes the student is taking THIS semester, from that curriculum:
    #: its courses and the electives they picked. Earlier semesters' courses
    #: are the curriculum's, not stored twice.
    courses: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    weekly_goal: int = 3
    #: "HH:MM", local to the student. Empty means no reminder.
    reminder_time: str = ""
    onboarded_at: datetime | None = None
    updated_at: datetime = Field(default_factory=utcnow)


# ─────────────────────────────────────────────────────────────
#  THE EPISODIC SUBSTRATE  (what evidence refs resolve against)
# ─────────────────────────────────────────────────────────────


class Artifact(SQLModel, table=True):
    """A turn, a code submission, a canvas — the thing a quote is quoted from.

    §5.1: in Phase 1 the evidence resolver reads M04's own episodic tier,
    because M19's ledger does not exist yet and AC-4.1 has to hold anyway.
    That makes the ledger a projection over this table later, not a
    prerequisite for it now.

    Immutable. A deletion writes `tombstoned_at` and clears `content` rather
    than removing the row, which is the ONLY way EC-4.9 stays distinguishable
    from a corrupt reference: "deleted on purpose" and "never existed" must not
    look the same to the resolver.
    """

    __tablename__ = "m04_artifacts"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    candidate_id: uuid.UUID = Field(index=True)
    session_id: uuid.UUID = Field(index=True)
    turn_id: uuid.UUID | None = Field(default=None, index=True)
    artifact_type: str = "transcript"
    content: str = ""
    checksum: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    tombstoned_at: datetime | None = None
    tombstone_reason: str | None = None


# ─────────────────────────────────────────────────────────────
#  THE WRITE PATH
# ─────────────────────────────────────────────────────────────


class Observation(SQLModel, table=True):
    """The ONLY way mastery changes. No evidence → no write.

    FR-4.5 lives in the type (`evidence` must be non-empty and every ref must
    resolve), not in a NOT NULL constraint — a column can hold `[]` and a
    constraint cannot check that a checksum still matches an artifact.
    """

    __tablename__ = "m04_observations"

    #: uuid5 content hash (§6.2). A replay from `observations_pending` is then
    #: an insert conflict rather than a second helping of the same evidence —
    #: without it the fallback path IS the corruption path.
    id: uuid.UUID = Field(primary_key=True)
    candidate_id: uuid.UUID = Field(index=True)
    concept_id: str = Field(index=True)
    #: Secondary concepts count less. Mirrors M05's ConceptWeight.
    concept_weight: float = 1.0
    session_id: uuid.UUID = Field(index=True)
    turn_id: uuid.UUID | None = None
    evidence: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
    kind: str = Field(index=True)

    # --- the response, in the form the likelihood actually needs ---
    response_model: str = ResponseModel.none
    #: The UN-normalised rubric level, 0..K. GRM's likelihood needs the
    #: category, not a normalised float: collapsing a 5-point rubric to
    #: right/wrong throws away most of the information and biases `b`.
    raw_category: int | None = None
    n_categories: int | None = None
    #: Normalised 0–1. DISPLAY and BKT only — never the likelihood.
    outcome: float = 0.0
    item: dict | None = Field(default=None, sa_column=Column(JSON))
    #: Derived at write time, stored, and shown in the evidence drawer, so a
    #: student can see which of their answers moved the number and which did
    #: not (EC-4.17).
    theta_eligible: bool = False
    #: Which M13 rubric dimension became this observation. Without it, "why is
    #: this value what it is" can name the answer but not the criterion.
    source_dimension_key: str | None = None
    #: Likelihood tempering, in (0, 1]. NEVER above 1: a weight > 1 fabricates
    #: precision that no answer supplied.
    weight: float = 1.0

    # --- propagation provenance (kind == "propagated") ---
    source_concept_id: str | None = None
    hops: int = 0
    #: FR-4.24. Propagated evidence never counts toward displayable mastery: a
    #: concept whose evidence is purely inherited renders `not_tested`.
    counts_toward_n_direct: bool = True

    # --- posterior after, so trajectories replay without re-running anything ---
    theta_after: float = 0.0
    se_after: float = 1.5

    # --- versions, consent, lifecycle ---
    versions: dict = Field(default_factory=dict, sa_column=Column(JSON))
    estimator_version: str = "1.0"
    ontology_version: str = "1.0"
    state_thresholds_version: str = "1.0"
    consent_id: uuid.UUID
    observed_at: datetime = Field(default_factory=utcnow, index=True)
    #: FR-4.26: mastery is RECOMPUTED from surviving observations, never
    #: compensated by an inverse update. An inverse update leaves two wrongs in
    #: the ledger and a right answer nobody can derive.
    retracted_at: datetime | None = None
    retraction_reason: str | None = None


class PendingObservation(SQLModel, table=True):
    """§10's fallback queue, in M04's OWN database.

    Anywhere else and the fallback fails together with the thing it was meant
    to survive.
    """

    __tablename__ = "m04_observations_pending"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    observation_id: uuid.UUID = Field(index=True)
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))
    failure: str = ""
    attempts: int = 0
    created_at: datetime = Field(default_factory=utcnow)
    replayed_at: datetime | None = None


class Mastery(SQLModel, table=True):
    """The durable posterior. One row per (candidate, concept).

    M04 owns this; M05 owns a session-scoped provisional theta that is never
    persisted and never displayed (§6.3). At session end the posterior wins
    silently, and a divergence > 0.5 logits is logged as a calibration signal.
    """

    __tablename__ = "m04_concept_mastery"

    candidate_id: uuid.UUID = Field(primary_key=True)
    concept_id: str = Field(primary_key=True)
    theta: float = 0.0
    #: The honesty channel. Prior 1.5. Persisted; `se_effective` is computed on
    #: read from `ai_core.mastery` and is what every display rule uses.
    se: float = 1.5
    n_direct: int = 0
    n_propagated: int = 0
    last_evidence_at: datetime | None = None
    #: From probe ladders: how deep the questioning got before understanding
    #: broke. Feeds Moment 1's opening line.
    break_depth_mean: float | None = None
    #: Lifetime propagated contribution, clamped at 0.35 logits (§6.4). Tracked
    #: rather than recomputed: ten failed DP questions must not be able to walk
    #: recursion's estimate anywhere on their own.
    theta_propagated_total: float = 0.0
    #: The hysteresis latch (§6.5). Once a bar has been shown to a student it
    #: is never un-shown by the passage of time — it greys and says when it was
    #: last checked. A vanishing bar is worse than a lowered one.
    ever_displayed: bool = False
    #: Optimistic lock. EC-4.15: two observations landing concurrently retry
    #: three times and then raise, rather than losing an update silently.
    version: int = 0
    ontology_version: str = "1.0"
    estimator_version: str = "1.0"
    updated_at: datetime = Field(default_factory=utcnow)
    #: EC-4.3: contradictory observations that persist get flagged for review
    #: rather than being averaged into a confident middle.
    flagged_inconsistent: bool = False


class OutboxEvent(SQLModel, table=True):
    """`mastery.updated`, drained AFTER commit (§6.2).

    `emit_event()` inside the transaction is a dual write: the event fires for
    work that may roll back. A table is enough here; Redis and a real queue are
    deferred until M06 needs one for its own reasons.
    """

    __tablename__ = "m04_outbox"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    topic: str = Field(index=True)
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)
    delivered_at: datetime | None = None


# ─────────────────────────────────────────────────────────────
#  MEMORY TIERS
# ─────────────────────────────────────────────────────────────


class MemoryFact(SQLModel, table=True):
    """A distilled fact about a student, written by the nightly distiller.

    Facts are SUPERSEDED, never deleted, so the episodic substrate stays the
    single re-derivable truth. A student's delete button sets
    `suppressed_until` and increments `delete_count` — see §8: three
    operations share the word "delete" and the UI says which one is happening.
    """

    __tablename__ = "m04_candidate_facts"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    candidate_id: uuid.UUID = Field(index=True)
    tier: str = Field(index=True)
    kind: str = Field(index=True)
    content: dict = Field(default_factory=dict, sa_column=Column(JSON))
    #: The shipped string, written at distillation and stored. §11 forbids an
    #: LLM on the read path, and Moment 1's opening line IS a read — so it is
    #: looked up, not composed at session start.
    display_sentence: str = ""
    #: Verbatim substring of a cited turn. Screen 2 of §6.6b: require the
    #: citation, then check it yourself.
    quote: str | None = None
    #: float32 bytes. A BLOB on SQLite, and the same bytes on Postgres until
    #: pgvector is worth the setup — every search is candidate-scoped over a
    #: few hundred rows, where brute-force cosine is sub-millisecond.
    embedding: bytes | None = Field(default=None, sa_column=Column(LargeBinary))
    embedding_model: str = ""
    embedding_version: str = ""
    importance: float = 0.2
    concept_ids: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    source_evidence: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
    produced_by_model: str = ""
    produced_by_prompt: str = ""
    purpose: str = Purpose.practice
    created_at: datetime = Field(default_factory=utcnow, index=True)
    superseded_by: uuid.UUID | None = None
    #: The student deleted it. Re-derivation is suppressed for 30 days, and a
    #: second deletion suppresses it forever — otherwise the nightly distiller
    #: quietly re-creates it and the button was a lie (§15.9, EC-4.20).
    suppressed_until: datetime | None = None
    delete_count: int = 0


class ProfileSummary(SQLModel, table=True):
    """The working tier: what an interviewer agent gets at session start.

    A table with a `stale` flag, NOT a materialised view — Postgres cannot
    refresh one incrementally, so "refreshed on write" was never implementable
    at any write rate. Redis is an optional accelerator, never a requirement.
    """

    __tablename__ = "m04_profile_summary"

    candidate_id: uuid.UUID = Field(primary_key=True)
    summary_text: str = ""
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))
    token_estimate: int = 0
    stale: bool = True
    built_at: datetime = Field(default_factory=utcnow)
    summary_version: str = "1.0"


class SessionProfileSnapshot(SQLModel, table=True):
    """FR-4.23: byte-identical for the life of a session.

    Written once when a session opens and served unchanged thereafter.
    `record()` marks the NEXT session's summary stale, never this one's. Two
    reasons, and the second is the expensive one: mutating prose mid-interview
    changes the interviewer's own context between its turns, and it invalidates
    M06's prompt cache on every observation — a real bill, not a purity
    argument. In-session movement already reaches the interviewer through the
    right channel: M05's selector reads live mastery.
    """

    __tablename__ = "m04_session_profile_snapshot"

    session_id: uuid.UUID = Field(primary_key=True)
    candidate_id: uuid.UUID = Field(index=True)
    summary_text: str = ""
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))
    summary_version: str = "1.0"
    ontology_version: str = "1.0"
    built_at: datetime = Field(default_factory=utcnow)


class RetestQueueItem(SQLModel, table=True):
    """§6.9. M04 owns this table; M05 reads it as a selection input and M16
    reads it in Phase 4 — it does not own it, or §2.4's promise ("we've queued
    a recursion question for your next session") cannot be kept until then."""

    __tablename__ = "m04_retest_queue"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    candidate_id: uuid.UUID = Field(index=True)
    concept_id: str = Field(index=True)
    reason: str = Field(index=True)
    requested_by: str = "M04"
    source_ref: dict = Field(default_factory=dict, sa_column=Column(JSON))
    priority: float = 1.0
    #: Overrides M05's 90-day no-repeat filter. Not a detail: without it a
    #: disputed value can never be re-tested, and §2.4's promise is empty.
    bypass_freshness: bool = True
    created_at: datetime = Field(default_factory=utcnow)
    #: Don't chase a re-test forever.
    expires_at: datetime | None = None
    resolved_at: datetime | None = None
    resolved_by_observation_id: uuid.UUID | None = None


class Dispute(SQLModel, table=True):
    """"This doesn't look right" (§2.4, FR-4.13, EC-4.7).

    Being wrong occasionally is survivable; being wrong and unaccountable is
    not. A dispute never argues back — it flags, queues a re-test, and reports
    what happened.
    """

    __tablename__ = "m04_disputes"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    candidate_id: uuid.UUID = Field(index=True)
    concept_id: str = Field(index=True)
    reason: str = ""
    theta_at_dispute: float = 0.0
    created_at: datetime = Field(default_factory=utcnow)
    resolved_at: datetime | None = None
    #: AC-4.7 reports the UPHELD rate, with n. "Dispute rate < 5%" was passed
    #: most easily by hiding the button.
    upheld: bool | None = None


# ─────────────────────────────────────────────────────────────
#  API SHAPES  (not tables)
# ─────────────────────────────────────────────────────────────


class RecordResult(BaseModel):
    applied: bool
    observation_id: uuid.UUID
    reason: str = ""
    theta_after: float | None = None
    se_after: float | None = None
    theta_eligible: bool = False
    propagated_to: list[str] = PydanticField(default_factory=list)


class MasteryOut(BaseModel):
    """What every consumer reads. `mastery_p` is None, never 0.0, when there is
    nothing to claim (AC-4.2)."""

    concept_id: str
    name: str
    domain: str
    state: str
    label: str
    mastery_p: float | None
    theta: float
    se: float
    se_effective: float
    n_direct: int
    n_propagated: int
    last_evidence_at: datetime | None
    stale: bool
    retest_queued: bool = False
    #: How many other concepts this one blocks. Only set where it was computed.
    blocks: int | None = None
