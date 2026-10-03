/**
 * M04 — Skill Graph & MNEMOS Memory · routes.
 *
 * One screen, at `/skills`, with the open concept in the query
 * (`?concept=concept:hashing`) so "look at what moved on hashing" is a link.
 * Platform_Shell mounts this same tree; `standalone.tsx` wraps it on :5204.
 */
import { Route } from "react-router-dom";

import { SkillGraphPage } from "./components/SkillGraphPage";

export const m04Routes = (
  <Route key="m04">
    <Route path="/skills" element={<SkillGraphPage />} />
  </Route>
);
