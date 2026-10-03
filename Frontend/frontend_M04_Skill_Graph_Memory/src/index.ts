/**
 * M04 — Skill Graph & MNEMOS Memory · public surface.
 *
 * The routes for the shell, and the hooks a sibling module would use to show
 * the same beliefs — read from here, never re-fetched by hand, so "untested is
 * not zero" stays true in every place a mastery bar is drawn.
 */
export { m04Routes } from "./routes";
export { SkillGraphPage } from "./components/SkillGraphPage";
export { m04Keys, useBottlenecks, useEvidence, useMastery } from "./api";
export { movesSince, snapshot } from "./movement";
export type {
  Bottleneck,
  EvidenceResponse,
  MasteryResponse,
  MasteryRow,
  Observation,
} from "./types";
