/**
 * "Why is this value what it is?" — Rule 3's escape hatch (FR-4.12), drawn —
 * and, since 2026-10-04, "how do I get better at it?".
 *
 * Every bar on the page opens this. It shows the student's own words where an
 * answer was scored, and a plain sentence where a belief was inherited from a
 * related concept through the graph. The estimator's numbers are still here,
 * folded under "Details": they are true and checkable, and to a student who
 * has not asked for them "−1.55 give or take 0.73" reads as an error.
 *
 * ── Learn ───────────────────────────────────────────────────────────────────
 * Finding out what is weak without a way to improve it was a dead end; the
 * only action anywhere was "take another interview". The Learn section is
 * built from what the platform already knows, and invents nothing:
 *
 *   · what the topic builds on, each with the student's own state on it — if
 *     a prerequisite is weak too, that is where to start, and the ontology's
 *     prerequisite edges are exactly that claim;
 *   · what it unlocks, so the payoff is visible;
 *   · the names it goes by, which is what a student searches for;
 *   · a focused interview on it (M06 plans one segment on these concepts);
 *   · a search link built from the name, for reading — M16's study plan,
 *     when it exists, replaces this with material someone has vetted.
 */
import { Link } from "react-router-dom";

import {
  ANSWER_BAND_LABEL,
  HowItWorks,
  Icon,
  MasteryBar,
  STATE_LABEL,
  Skeleton,
  answerBand,
  shortDate,
} from "@ai/core";

import { useConcept, useEvidence } from "../api";
import type { MasteryRow, Observation } from "../types";

const LEVEL_LABEL: Record<string, string> = {
  foundational: "Foundation",
  intermediate: "Intermediate",
  advanced: "Advanced",
};

const BAND_TONE = {
  strong: "text-mastery-strong",
  partly: "text-mastery-ok",
  not_yet: "text-mastery-weak",
} as const;

function Details({ row }: { row: MasteryRow }) {
  const se = row.se_effective ?? row.se;
  return (
    <HowItWorks label="Details">
      <p>
        {row.n_direct ?? 0} answer{row.n_direct === 1 ? "" : "s"} on this topic directly, and{" "}
        {row.n_propagated} inherited from related topics.
      </p>
      {row.theta !== null ? (
        <p>
          The estimate behind the bar is{" "}
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
          )}{" "}
          on a scale where 0 is a typical student. The give-or-take widens with time since your
          last answer.
        </p>
      ) : (
        <p>No estimate yet — only counts. One scored answer starts it.</p>
      )}
    </HowItWorks>
  );
}

function ObservationItem({ obs }: { obs: Observation }) {
  const quote = obs.evidence.find((e) => e.span?.quote)?.span?.quote;
  const turn = obs.evidence.find((e) => e.turn_id)?.turn_id;
  const direct = obs.kind !== "propagated";
  const band = obs.outcome !== null ? answerBand(obs.outcome) : null;
  return (
    <li className={`border-l-2 pl-3 ${direct ? "border-brand-line" : "border-line"} ${obs.retracted ? "opacity-50" : ""}`}>
      <p className="text-xs text-ink-faint">
        {shortDate(obs.observed_at)} · {direct ? "an answer you gave" : "from a related topic"}
        {band && (
          <>
            {" · "}
            <span className={`font-medium ${BAND_TONE[band]}`}>{ANSWER_BAND_LABEL[band]}</span>
          </>
        )}
        {obs.retracted && <> · withdrawn</>}
      </p>
      {quote && (
        <blockquote className="mt-1.5 text-sm leading-relaxed text-ink">“{quote}”</blockquote>
      )}
      {!quote && obs.note && <p className="mt-1 text-sm text-ink-soft">{obs.note}</p>}
      {direct && turn && (
        <Link to={`/turns/${turn}`} className="mt-1 inline-block text-xs font-medium text-brand">
          How this answer was marked →
        </Link>
      )}
    </li>
  );
}

function Learn({ row, rows }: { row: MasteryRow; rows: MasteryRow[] }) {
  const concept = useConcept(row.concept_id);
  const stateOf = new Map(rows.map((r) => [r.concept_id, r.state]));
  const prereqs = concept.data?.prerequisites ?? [];
  const weakUnder = prereqs.filter((p) => stateOf.get(p.concept_id) === "weak");
  const search = `https://www.google.com/search?q=${encodeURIComponent(
    `${row.name} ${concept.data?.domain === "communication" ? "interview tips" : "explained with examples"}`,
  )}`;
  const practise = `/mock?focus=${encodeURIComponent(row.concept_id)}&label=${encodeURIComponent(row.name)}`;

  return (
    <section aria-labelledby="learn-heading">
      <h3 id="learn-heading" className="flex items-center gap-2 text-sm font-semibold text-ink">
        <Icon name="sparkles" size={15} className="text-brand" />
        Get better at {row.name}
      </h3>

      <div className="mt-3 flex flex-wrap gap-2">
        <Link
          to={practise}
          className="inline-flex h-9 items-center gap-2 rounded-lg bg-brand px-3.5 text-sm font-semibold text-white hover:bg-brand-hover"
        >
          <Icon name="mic" size={15} />
          Practise this topic
        </Link>
        <a
          href={search}
          target="_blank"
          rel="noreferrer"
          className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-line px-3 text-sm font-medium text-ink-soft hover:border-line-strong hover:text-ink"
        >
          <Icon name="search" size={15} />
          Read up on it
        </a>
      </div>

      {concept.isLoading && (
        <div className="mt-4 space-y-2" role="status" aria-label="Loading what this topic builds on">
          <Skeleton className="h-3 w-1/3" />
          <Skeleton className="h-3 w-2/3" />
        </div>
      )}

      {concept.data && (
        <dl className="mt-4 space-y-3 text-sm">
          {weakUnder.length > 0 && (
            <p className="rounded-lg border border-mastery-weak/40 bg-surface-sunken p-3 text-ink-soft">
              If it feels hard, the gap may be underneath:{" "}
              <span className="font-medium text-ink">{weakUnder.map((p) => p.name).join(", ")}</span>{" "}
              {weakUnder.length === 1 ? "needs" : "need"} work too. Start there.
            </p>
          )}
          {prereqs.length > 0 && (
            <div>
              <dt className="text-xs font-medium text-ink-faint">Builds on</dt>
              <dd className="mt-1.5 flex flex-wrap gap-1.5">
                {prereqs.map((p) => {
                  const state = stateOf.get(p.concept_id);
                  return (
                    <span
                      key={p.concept_id}
                      className="inline-flex items-center gap-1.5 rounded-full border border-line px-2.5 py-1 text-xs text-ink"
                    >
                      {p.name}
                      <span className="text-ink-faint">· {state ? STATE_LABEL[state] : "not tested yet"}</span>
                    </span>
                  );
                })}
              </dd>
            </div>
          )}
          {concept.data.unlocks.length > 0 && (
            <div>
              <dt className="text-xs font-medium text-ink-faint">Unlocks</dt>
              <dd className="mt-1 text-ink-soft">
                {concept.data.unlocks.map((u) => u.name).join(", ")}
              </dd>
            </div>
          )}
          {concept.data.aliases.length > 0 && (
            <div>
              <dt className="text-xs font-medium text-ink-faint">Also called</dt>
              <dd className="mt-1 text-ink-soft">{concept.data.aliases.slice(0, 6).join(" · ")}</dd>
            </div>
          )}
        </dl>
      )}
    </section>
  );
}

export function EvidenceDrawer({
  candidate,
  row,
  rows,
  onClose,
}: {
  candidate: string;
  row: MasteryRow;
  /** Every measured row, so the Learn section can show a prerequisite's state. */
  rows: MasteryRow[];
  onClose: () => void;
}) {
  const evidence = useEvidence(candidate, row.concept_id);
  const observations = evidence.data?.observations ?? [];
  const concept = useConcept(row.concept_id);
  const level = concept.data ? LEVEL_LABEL[concept.data.level] : undefined;

  return (
    <aside
      aria-label={row.name}
      className="panel sticky top-20 flex max-h-[calc(100dvh-6rem)] flex-col overflow-hidden"
    >
      <header className="border-b border-line p-5">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            {level && <p className="text-xs font-medium text-ink-faint">{level}</p>}
            <h2 className="mt-0.5 text-section font-semibold text-ink">{row.name}</h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="grid h-8 w-8 place-items-center rounded-md text-ink-faint hover:bg-surface-sunken hover:text-ink"
          >
            <Icon name="close" size={16} />
          </button>
        </div>
        <div className="mt-3">
          <MasteryBar value={row} width="w-48" />
        </div>
        {row.retest_queued && (
          <p className="mt-2 text-xs text-ink-faint">
            A fresh question on this is waiting in your next interview.
          </p>
        )}
        <Details row={row} />
      </header>

      <div className="flex-1 space-y-7 overflow-y-auto p-5">
        <Learn row={row} rows={rows} />

        <section>
          <h3 className="text-sm font-semibold text-ink">Your answers on this</h3>
          {evidence.isLoading && (
            <div className="mt-3 space-y-3" role="status" aria-label="Loading your answers">
              <Skeleton className="h-3 w-1/4" />
              <Skeleton className="h-12 w-full" />
            </div>
          )}
          {evidence.error && (
            <p className="mt-3 text-sm text-contested">{(evidence.error as Error).message}</p>
          )}
          {!evidence.isLoading && observations.length === 0 && !evidence.error && (
            <p className="mt-3 text-sm text-ink-soft">
              None yet. “{STATE_LABEL[row.state]}” is a starting guess from related topics, not a
              measurement.
            </p>
          )}
          <ol className="mt-3 space-y-4">
            {observations.map((obs) => (
              <ObservationItem key={obs.observation_id} obs={obs} />
            ))}
          </ol>
        </section>
      </div>
    </aside>
  );
}
