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

export interface EvidenceResponse {
  concept_id: string;
  bkt_p_known: number | null;
  observations: Observation[];
}
