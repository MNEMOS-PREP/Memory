/**
 * "Why is this value what it is?" — Rule 3's escape hatch (FR-4.12), drawn.
 *
 * Every bar on the page opens this. It shows the posterior with its error —
 * the only place on the screen a number appears, because only here does it
 * stand next to what produced it — and every observation behind it: the
 * student's own words where an answer was scored, and a plain sentence where
 * a belief was inherited from a related concept through the graph.
 */
import { Link } from "react-router-dom";

import { MasteryBar, STATE_LABEL, shortDate } from "@ai/core";

import { useEvidence } from "../api";
import type { MasteryRow, Observation } from "../types";

function Posterior({ row }: { row: MasteryRow }) {
  if (row.theta === null) {
    return <p className="text-sm text-ink-soft">No ability estimate yet — only counts.</p>;
  }
  const se = row.se_effective ?? row.se;
  return (
    <p className="text-sm text-ink-soft">
      Ability estimate{" "}
      <span className="font-mono text-ink" data-numeric>
        {row.theta.toFixed(2)}
      </span>
      {se !== null && (
        <>
          {" "}
          give or take{" "}
          <span className="font-mono text-ink" data-numeric>
            {se.toFixed(2)}
          </span>
        </>
      )}
      <span className="text-ink-faint">
        {" "}
        · {row.n_direct ?? 0} answered directly, {row.n_propagated} inherited
      </span>
    </p>
  );
}

function ObservationItem({ obs }: { obs: Observation }) {
  const quote = obs.evidence.find((e) => e.span?.quote)?.span?.quote;
  const turn = obs.evidence.find((e) => e.turn_id)?.turn_id;
  const direct = obs.kind !== "propagated";
  return (
    <li className={`border-l-2 pl-3 ${direct ? "border-brand-line" : "border-line"} ${obs.retracted ? "opacity-50" : ""}`}>
      <p className="text-xs text-ink-faint">
        {shortDate(obs.observed_at)} · {direct ? "an answer you gave" : "inherited from a related topic"}
        {obs.outcome !== null && <> · scored {Math.round(obs.outcome * 100)}%</>}
        {obs.retracted && <> · retracted</>}
        {!obs.moved_the_estimate && direct && <> · counted, did not move the estimate</>}
      </p>
      {quote && (
        <blockquote className="mt-1.5 text-sm leading-relaxed text-ink">“{quote}”</blockquote>
      )}
      {!quote && obs.note && <p className="mt-1 text-sm text-ink-soft">{obs.note}</p>}
      {direct && turn && (
        <Link to={`/turns/${turn}`} className="mt-1 inline-block text-xs font-medium text-brand">
          How this answer was scored →
        </Link>
      )}
    </li>
  );
}

export function EvidenceDrawer({
  candidate,
  row,
  onClose,
}: {
  candidate: string;
  row: MasteryRow;
  onClose: () => void;
}) {
  const evidence = useEvidence(candidate, row.concept_id);
  const observations = evidence.data?.observations ?? [];

  return (
    <aside
      aria-label={`Evidence for ${row.name}`}
      className="panel sticky top-6 flex max-h-[calc(100vh-3rem)] flex-col overflow-hidden"
    >
      <header className="border-b border-line p-5">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <p className="provenance">{row.domain} · {row.concept_id}</p>
            <h2 className="mt-1 text-section font-semibold text-ink">{row.name}</h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close the evidence"
            className="rounded-md px-2 py-1 text-sm text-ink-faint hover:bg-surface-sunken hover:text-ink"
          >
            ✕
          </button>
        </div>
        <div className="mt-3">
          <MasteryBar value={row} width="w-48" />
        </div>
        <div className="mt-3">
          <Posterior row={row} />
        </div>
        {row.retest_queued && (
          <p className="mt-2 text-xs text-ink-faint">
            A fresh question on this is queued for your next session.
          </p>
        )}
      </header>

      <div className="flex-1 overflow-y-auto p-5">
        <h3 className="rule-label">What it rests on</h3>
        {evidence.isLoading && <p className="mt-3 text-sm text-ink-faint">Loading the evidence…</p>}
        {evidence.error && (
          <p className="mt-3 text-sm text-contested">{(evidence.error as Error).message}</p>
        )}
        {!evidence.isLoading && observations.length === 0 && !evidence.error && (
          <p className="mt-3 text-sm text-ink-soft">
            Nothing yet. “{STATE_LABEL[row.state]}” here is the graph's prior, not a measurement.
          </p>
        )}
        <ol className="mt-3 space-y-4">
          {observations.map((obs) => (
            <ObservationItem key={obs.observation_id} obs={obs} />
          ))}
        </ol>
      </div>
    </aside>
  );
}
