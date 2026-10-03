/**
 * What moved since this page opened.
 *
 * The screen's job in the product is "watch what you know change", and a
 * belief that changed while you were answering somewhere else is the one
 * thing worth putting first. A baseline is taken on the first answer the page
 * gets, and every later answer is compared to it — not to the previous poll,
 * so a concept that moved stays marked until the page is reloaded.
 *
 * A move is new EVIDENCE, not a new number: `n_direct` going up, the state
 * word changing, or θ shifting. The bar's width alone is not compared, because
 * an `emerging` concept has no width to compare (it is not displayable yet),
 * and that is exactly the state a first interview produces.
 */
import type { MasteryRow } from "./types";

export interface Snapshot {
  theta: number | null;
  n_direct: number;
  state: string;
}

export interface Move {
  row: MasteryRow;
  /** First evidence ever for this concept, during this visit. */
  isNew: boolean;
  /** θ after minus θ at baseline; null when either side has none. */
  thetaDelta: number | null;
  /** Answers that reached it directly since the baseline. */
  newEvidence: number;
  stateFrom: string | null;
}

export function snapshot(rows: MasteryRow[]): Map<string, Snapshot> {
  return new Map(
    rows.map((r) => [r.concept_id, { theta: r.theta, n_direct: r.n_direct ?? 0, state: r.state }]),
  );
}

/** Below this a θ change is arithmetic noise, not a move worth showing. */
const THETA_EPSILON = 1e-6;

export function movesSince(baseline: Map<string, Snapshot> | null, rows: MasteryRow[]): Move[] {
  if (!baseline) return [];
  const moves: Move[] = [];
  for (const row of rows) {
    const before = baseline.get(row.concept_id);
    if (!before) {
      moves.push({ row, isNew: true, thetaDelta: null, newEvidence: row.n_direct ?? 0, stateFrom: null });
      continue;
    }
    const thetaDelta =
      row.theta !== null && before.theta !== null ? row.theta - before.theta : null;
    const newEvidence = (row.n_direct ?? 0) - before.n_direct;
    const stateChanged = row.state !== before.state;
    if (newEvidence > 0 || stateChanged || (thetaDelta !== null && Math.abs(thetaDelta) > THETA_EPSILON)) {
      moves.push({
        row,
        isNew: false,
        thetaDelta,
        newEvidence,
        stateFrom: stateChanged ? before.state : null,
      });
    }
  }
  return moves;
}

/** Up, down or flat, in words a student reads — never a bare number. */
export function direction(delta: number | null): "up" | "down" | "flat" {
  if (delta === null || Math.abs(delta) < 0.01) return "flat";
  return delta > 0 ? "up" : "down";
}
