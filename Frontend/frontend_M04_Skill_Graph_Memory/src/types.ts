/**
 * M04's read shapes, as the backend serves them (router.py §7).
 *
 * `MasteryRow` is core's `MasteryValue` plus what this module alone knows — the
 * posterior behind the state word. Core's bar renders the state; the numbers
 * stay here, in the evidence drawer, where they can be read with their error.
 */
import type { MasteryValue } from "@ai/core";

export interface MasteryRow extends MasteryValue {
  domain: string;
  label: string;
  /** IRT posterior: the single source of truth for this concept (§6). */
  theta: number | null;
  se: number | null;
  /** SE widened for time since the last evidence — what decay looks like. */
  se_effective: number | null;
  /** Observations that reached this concept from a related one. */
  n_propagated: number;
  retest_queued: boolean;
}

export interface MasteryResponse {
  ontology_version: string;
  measured: MasteryRow[];
  /** A count and the names — never 112 empty rows (EC-4.1). */
  not_yet_tested: { count: number; names: string[] };
  totals: { measured: number; in_ontology: number };
}

export interface Bottleneck {
  concept_id: string;
  name: string;
  domain: string;
  /** How many of this student's weak topics it sits underneath. */
  blocks: number;
  weighted_blocks: number;
  theta: number | null;
  se: number | null;
  n_direct: number;
}

export interface BottlenecksResponse {
  bottlenecks: Bottleneck[];
  /** Said when there are none, because "none" and "could not tell" differ. */
  reason: string | null;
}

export interface EvidenceSpan {
  artifact_type: string;
  artifact_id: string;
  start: number;
  end: number;
  quote: string;
  verified: boolean;
}

export interface EvidenceRef {
  kind: string;
  session_id: string | null;
  turn_id: string | null;
  span: EvidenceSpan | null;
}

export interface Observation {
  observation_id: string;
  /** `answer_scored` is the student's own answer; `propagated` came from a
   *  related concept through the graph. */
  kind: string;
  observed_at: string;
  session_id: string | null;
  outcome: number | null;
  theta_after: number | null;
  se_after: number | null;
  moved_the_estimate: boolean;
  retracted: boolean;
  evidence: EvidenceRef[];
  note?: string | null;
}

export interface TrajectoryPoint {
  observed_at: string;
  theta: number | null;
  se: number | null;
  kind: string;
}

/** `/trajectory`: every concept's history on the scale it was scored on. */
export interface TrajectoryResponse {
  candidate_id: string;
  series: { concept_id: string; name: string; points: TrajectoryPoint[] }[];
}

export interface EvidenceResponse {
  concept_id: string;
  bkt_p_known: number | null;
  observations: Observation[];
}

/** `/v1/concepts/{id}`: the ontology's entry, with its neighbours named. */
export interface ConceptNeighbour {
  concept_id: string;
  name: string;
  strength: number;
  hops: number;
}

export interface ConceptDetail {
  id: string;
  name: string;
  domain: string;
  level: string;
  aliases: string[];
  typical_question_time_s: number;
  prerequisites: ConceptNeighbour[];
  unlocks: ConceptNeighbour[];
}

/** FR-4.20: what a student has agreed to, per purpose. */
export interface ConsentRecord {
  consent_id: string;
  candidate_id: string;
  purpose: string;
  policy_version: string;
  granted_at: string;
  revoked_at: string | null;
  active: boolean;
}

export interface ProfileCompany {
  name: string;
  company_id?: string | null;
}

export interface ProfileDrive {
  label: string;
  /** `YYYY-MM-DD`. */
  date: string;
  company_id?: string | null;
  /** M15's drive variant, when picked: what a drive-specific mock plans from. */
  drive_id?: string | null;
}

/** What the student said they are preparing for (2026-10-04). Their answers,
 *  nothing inferred. */
export interface StudentProfile {
  candidate_id: string;
  display_name: string;
  target_role: string;
  companies: ProfileCompany[];
  /** Soonest first. */
  drives: ProfileDrive[];
  year: string;
  branch: string;
  /** An id from `/v1/curricula`, or "" for a programme without one. */
  curriculum_id: string;
  /** 1-8; null when not said, or graduated. */
  semester: number | null;
  /** Course codes the student is taking this semester, electives included. */
  courses: string[];
  weekly_goal: number;
  /** `HH:MM`, or empty for no reminder. */
  reminder_time: string;
  onboarded_at: string | null;
  updated_at: string;
}

/* ── curricula: what the sign-in step offers (2026-10-13) ─────────────────── */

export interface CurriculumSummary {
  id: string;
  name: string;
  /** The department's code prefix: "CSE", "AIE". */
  short: string;
  institution: string;
  curriculum_year: number | null;
  semesters: number;
}

/** A concept a course's syllabus teaches, with the syllabus words behind it. */
export interface CourseConcept {
  id: string;
  name: string;
  hits: number;
  matched: string[];
}

export interface Course {
  code: string;
  title: string;
  /** The curriculum's category: SCI, ENGG, CSE, HUM, PRJ. */
  category: string | null;
  ltp: string | null;
  credits: string | null;
  /** Most taught first. Empty for a course with nothing an interview asks. */
  concepts: CourseConcept[];
}

/** "Professional Elective I": a place in a semester the student fills. */
export interface ElectiveSlot {
  kind: "professional" | "free" | "value";
  title: string;
  credits: string | null;
}

export interface Semester {
  number: number;
  courses: Course[];
  slots: ElectiveSlot[];
}

export interface ElectiveBasket {
  name: string;
  kind: "professional";
  courses: Course[];
}

export interface Curriculum extends Omit<CurriculumSummary, "semesters"> {
  source: { file: string; sha256: string; pages: number };
  ontology_version: string;
  semesters: Semester[];
  electives: ElectiveBasket[];
}

export type ProfileUpdate = Partial<
  Omit<StudentProfile, "candidate_id" | "onboarded_at" | "updated_at">
> & { onboarded?: boolean };
