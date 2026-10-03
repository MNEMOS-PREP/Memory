/**
 * The skill graph — M04's first screen (2026-10-03).
 *
 * Until now the platform's whole argument ended in a module nobody could see:
 * an interview was scored, M13 posted observations, M04 moved its beliefs, and
 * the only way to show it was `curl`. This is the student's own view of what
 * the platform believes about them, and it is built to be left open:
 *
 *   · It polls while open, and puts what MOVED since the page opened first —
 *     answer a question in the mock interview, come back, and the concept it
 *     touched is at the top with how far it moved.
 *   · "What is blocking you" is M04's bottleneck query: the weak concept
 *     sitting under the most other weak ones, which is where to start.
 *   · Every bar opens its evidence. Untested is never zero; it is a count,
 *     listed apart (EC-4.1), with the way to test it next to it.
 *
 * Whose graph: the signed-in student's. A placement officer is refused an
 * individual record by the backend (§15 decision 4 is unresolved), so the
 * screen says so rather than asking. An administrator sees the seeded student.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import {
  MasteryBar,
  NotYetTested,
  ROLE_LABEL,
  SEEDED_CANDIDATE_ID,
  STATE_LABEL,
  candidateIdOf,
  relativeDays,
  useSession,
} from "@ai/core";

import { useBottlenecks, useMastery } from "../api";
import { direction, movesSince, snapshot, type Move, type Snapshot } from "../movement";
import type { MasteryRow } from "../types";
import { EvidenceDrawer } from "./EvidenceDrawer";

/** The ontology's three domains; a fourth falls back to its own id. */
const DOMAIN_LABEL: Record<string, string> = {
  dsa: "Data structures & algorithms",
  cs_core: "CS fundamentals",
  communication: "Communication",
};

function domainLabel(domain: string): string {
  return DOMAIN_LABEL[domain] ?? domain.replace(/_/g, " ");
}

function MoveNote({ move }: { move: Move }) {
  if (move.isNew) return <span className="text-confirmed">first evidence</span>;
  const dir = direction(move.thetaDelta);
  return (
    <span className={dir === "down" ? "text-contested" : dir === "up" ? "text-confirmed" : "text-ink-soft"}>
      {move.stateFrom && (
        <>
          {STATE_LABEL[move.stateFrom as MasteryRow["state"]] ?? move.stateFrom} → {STATE_LABEL[move.row.state]}
          {" · "}
        </>
      )}
      {dir === "up" ? "▲ up" : dir === "down" ? "▼ down" : "held"}
      {move.newEvidence > 0 && <> · {move.newEvidence} new answer{move.newEvidence > 1 ? "s" : ""}</>}
    </span>
  );
}

function Row({
  row,
  open,
  onOpen,
  move,
}: {
  row: MasteryRow;
  open: boolean;
  onOpen: () => void;
  move?: Move;
}) {
  return (
    <li
      className={`flex flex-wrap items-center gap-x-4 gap-y-1.5 rounded-lg px-3 py-2.5 ${
        open ? "bg-brand-soft" : move ? "bg-confirmed-soft/60" : "hover:bg-surface-sunken/70"
      }`}
    >
      <button
        type="button"
        onClick={onOpen}
        className="min-w-[11rem] flex-1 text-left text-sm font-medium text-ink hover:text-brand"
      >
        {row.name}
      </button>
      <MasteryBar value={row} width="w-36 sm:w-44" onClick={onOpen} />
      {move && (
        <span className="w-full text-xs sm:w-auto">
          <MoveNote move={move} />
        </span>
      )}
    </li>
  );
}

export function SkillGraphPage() {
  const session = useSession();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [live, setLive] = useState(true);

  const own = candidateIdOf(session);
  const candidate = own ?? (session?.role === "admin" ? SEEDED_CANDIDATE_ID : null);

  const mastery = useMastery(candidate, live);
  const bottlenecks = useBottlenecks(candidate, live);

  // The first answer this visit got, and nothing after it.
  const baseline = useRef<Map<string, Snapshot> | null>(null);
  useEffect(() => {
    if (mastery.data && baseline.current === null) baseline.current = snapshot(mastery.data.measured);
  }, [mastery.data]);

  const rows = mastery.data?.measured ?? [];
  const moves = useMemo(() => movesSince(baseline.current, rows), [rows]);
  const movedById = useMemo(() => new Map(moves.map((m) => [m.row.concept_id, m])), [moves]);

  const byDomain = useMemo(() => {
    const groups = new Map<string, MasteryRow[]>();
    for (const row of rows) groups.set(row.domain, [...(groups.get(row.domain) ?? []), row]);
    return [...groups.entries()].sort((a, b) => b[1].length - a[1].length);
  }, [rows]);

  const openId = params.get("concept");
  const openRow = rows.find((r) => r.concept_id === openId) ?? null;
  const open = (id: string | null) => {
    const next = new URLSearchParams(params);
    if (id) next.set("concept", id);
    else next.delete("concept");
    setParams(next, { replace: true });
  };

  const latest = rows.reduce<string | null>(
    (acc, r) => (r.last_evidence_at && (!acc || r.last_evidence_at > acc) ? r.last_evidence_at : acc),
    null,
  );

  if (!candidate) {
    return (
      <div className="mx-auto max-w-2xl py-10">
        <p className="rule-label">Skill graph</p>
        <h1 className="mt-2 text-title font-semibold text-ink">This is a student's own view.</h1>
        <p className="mt-3 leading-relaxed text-ink-soft">
          {session
            ? `Signed in as ${ROLE_LABEL[session.role].toLowerCase()}. Placement staff see cohort figures, not one student's beliefs — whether that changes is the placement cell's policy to set, not a screen's.`
            : "Sign in as a student to see what the platform believes you know."}
        </p>
      </div>
    );
  }

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_26rem]">
      <div className="min-w-0">
        {/* ---------- header ---------- */}
        <header className="border-b border-line pb-7">
          <p className="rule-label">Skill graph · M04</p>
          <h1 className="mt-2.5 text-display font-semibold text-ink">What you know</h1>
          <p className="mt-3 max-w-2xl leading-relaxed text-ink-soft">
            Every bar is a belief with the answers behind it — open one to see them. Nothing
            untested is shown as a zero.
            {!own && " You are viewing the seeded student as an administrator."}
          </p>
          <dl className="mt-6 flex flex-wrap items-end gap-x-10 gap-y-4">
            <div>
              <dt className="text-2xl font-semibold tracking-tight text-ink" data-numeric>
                {mastery.data ? mastery.data.totals.measured : "—"}
              </dt>
              <dd className="mt-0.5 text-xs text-ink-faint">
                concepts measured of {mastery.data?.totals.in_ontology ?? "—"}
              </dd>
            </div>
            <div>
              <dt className="text-2xl font-semibold tracking-tight text-ink">
                {latest ? relativeDays(latest) : "—"}
              </dt>
              <dd className="mt-0.5 text-xs text-ink-faint">last new evidence</dd>
            </div>
            <div className="ml-auto">
              <button
                type="button"
                onClick={() => setLive(!live)}
                className="flex items-center gap-2 rounded-full border border-line px-3 py-1.5 text-xs text-ink-soft hover:border-line-strong"
              >
                <span
                  aria-hidden
                  className={`h-2 w-2 rounded-full ${live ? "animate-pulse bg-confirmed" : "bg-line-strong"}`}
                />
                {live ? "Updating live" : "Paused"}
              </button>
            </div>
          </dl>
        </header>

        {mastery.error && (
          <p role="alert" className="mt-6 rounded-lg border border-contested-line bg-contested-soft p-4 text-sm text-contested">
            {(mastery.error as Error).message}
          </p>
        )}
        {mastery.isLoading && <p className="mt-6 text-sm text-ink-faint">Reading your skill graph…</p>}

        {/* ---------- what moved ---------- */}
        {moves.length > 0 && (
          <section className="mt-7 rounded-panel border border-confirmed-line bg-confirmed-soft/40 p-5">
            <h2 className="text-section font-semibold text-ink">Moved since you opened this page</h2>
            <p className="mt-1 text-sm text-ink-soft">
              New evidence arrived — from an interview, scored and sent here while you watched.
            </p>
            <ul className="mt-3 space-y-0.5">
              {moves.map((m) => (
                <Row
                  key={m.row.concept_id}
                  row={m.row}
                  move={m}
                  open={openId === m.row.concept_id}
                  onOpen={() => open(m.row.concept_id)}
                />
              ))}
            </ul>
          </section>
        )}

        {/* ---------- what blocks ---------- */}
        {bottlenecks.data && bottlenecks.data.bottlenecks.length > 0 && (
          <section className="panel mt-7 p-5">
            <h2 className="text-section font-semibold text-ink">What is blocking you</h2>
            <p className="mt-1 text-sm text-ink-soft">
              The weak concept underneath the most of your other weak ones. Fix it first and the
              rest get easier.
            </p>
            <ol className="mt-4 space-y-2">
              {bottlenecks.data.bottlenecks.slice(0, 3).map((b, i) => (
                <li key={b.concept_id} className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                  <span className="font-mono text-xs text-ink-faint">{i + 1}</span>
                  <button
                    type="button"
                    onClick={() => open(b.concept_id)}
                    className="font-medium text-ink hover:text-brand"
                  >
                    {b.name}
                  </button>
                  <span className="text-xs text-ink-faint">
                    underneath {b.blocks} topic{b.blocks === 1 ? "" : "s"} · tested {b.n_direct}×
                  </span>
                </li>
              ))}
            </ol>
            <Link to="/mock" className="mt-4 inline-block text-sm font-medium text-brand">
              Practise it in a mock interview →
            </Link>
          </section>
        )}

        {/* ---------- everything measured ---------- */}
        {byDomain.map(([domain, domainRows]) => (
          <section key={domain} className="mt-8">
            <h2 className="rule-label">
              {domainLabel(domain)} <span className="text-ink-faint">· {domainRows.length}</span>
            </h2>
            <ul className="mt-2 space-y-0.5">
              {domainRows.map((row) => (
                <Row
                  key={row.concept_id}
                  row={row}
                  move={movedById.get(row.concept_id)}
                  open={openId === row.concept_id}
                  onOpen={() => open(row.concept_id)}
                />
              ))}
            </ul>
          </section>
        ))}

        {mastery.data && rows.length === 0 && (
          <section className="panel mt-8 p-6">
            <h2 className="text-section font-semibold text-ink">Nothing measured yet</h2>
            <p className="mt-2 text-sm leading-relaxed text-ink-soft">
              The graph starts empty on purpose: a belief needs an answer behind it. Take a mock
              interview and come back — this page updates while it is open.
            </p>
            <Link to="/mock" className="mt-4 inline-block text-sm font-medium text-brand">
              Start a mock interview →
            </Link>
          </section>
        )}

        {mastery.data && (
          <div className="mt-8">
            <NotYetTested names={mastery.data.not_yet_tested.names} onStartCheck={() => navigate("/mock")} />
          </div>
        )}
      </div>

      {/* ---------- the evidence ---------- */}
      <div className="min-w-0">
        {openRow ? (
          <EvidenceDrawer candidate={candidate} row={openRow} onClose={() => open(null)} />
        ) : (
          rows.length > 0 && (
            <p className="hidden rounded-panel border border-dashed border-line p-5 text-sm text-ink-faint xl:block">
              Open any concept to see the answers it rests on.
            </p>
          )
        )}
      </div>
    </div>
  );
}
