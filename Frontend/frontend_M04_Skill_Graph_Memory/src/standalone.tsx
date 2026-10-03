/**
 * M04 running alone on :5204.
 *
 * Same routes and components as the shell mounts — this file only supplies the
 * providers the shell would otherwise own.
 */

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { SEEDED_CANDIDATE_ID, ensureSession } from "@ai/core";

import { m04Routes } from "./routes";
// One stylesheet, on purpose — see the note in it.
import "./ui/theme.css";

// Alone there is no sign-in screen — that is Platform_Shell's — so with nobody
// signed in this is the seeded student, the one `Backend/seed.py` writes
// (`@ai/core`'s session, v0.12.0).
ensureSession({ role: "student", subject: SEEDED_CANDIDATE_ID });

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 5_000, retry: 1, refetchOnWindowFocus: true },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <main className="mx-auto w-full max-w-[92rem] px-5 py-8 md:px-9">
          <Routes>
            {m04Routes}
            <Route path="*" element={<Navigate to="/skills" replace />} />
          </Routes>
        </main>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
