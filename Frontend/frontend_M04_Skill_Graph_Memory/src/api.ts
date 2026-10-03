/**
 * M04 over `@ai/core`'s fetch wrapper, which carries the session's identity.
 * Every route here is the student's own record; the backend refuses anybody
 * else (Platform_Core's candidate guard), and these hooks render its sentence.
 */
import { useQuery } from "@tanstack/react-query";

import { api } from "@ai/core";

import type {
  BottlenecksResponse,
  EvidenceResponse,
  MasteryResponse,
  TrajectoryResponse,
} from "./types";

export const m04Keys = {
  mastery: (candidate: string) => ["m04", "mastery", candidate] as const,
  bottlenecks: (candidate: string) => ["m04", "bottlenecks", candidate] as const,
  evidence: (candidate: string, concept: string) =>
    ["m04", "evidence", candidate, concept] as const,
  trajectory: (candidate: string) => ["m04", "trajectory", candidate] as const,
};

/**
 * `live` polls every five seconds. The point of the screen in a demo is to be
 * open while an interview is scored somewhere else, and to move when it is.
 */
export function useMastery(candidate: string | null, live: boolean) {
  return useQuery({
    queryKey: m04Keys.mastery(candidate ?? ""),
    enabled: Boolean(candidate),
    queryFn: () => api.get<MasteryResponse>(`/v1/candidates/${candidate}/mastery`),
    refetchInterval: live ? 5_000 : false,
  });
}

export function useBottlenecks(candidate: string | null, live: boolean) {
  return useQuery({
    queryKey: m04Keys.bottlenecks(candidate ?? ""),
    enabled: Boolean(candidate),
    queryFn: () => api.get<BottlenecksResponse>(`/v1/candidates/${candidate}/bottlenecks`),
    refetchInterval: live ? 15_000 : false,
  });
}

export function useEvidence(candidate: string | null, concept: string | null) {
  return useQuery({
    queryKey: m04Keys.evidence(candidate ?? "", concept ?? ""),
    enabled: Boolean(candidate && concept),
    queryFn: () =>
      api.get<EvidenceResponse>(
        `/v1/candidates/${candidate}/mastery/${encodeURIComponent(concept ?? "")}/evidence`,
      ),
  });
}

/** Every concept's history — what "growing over time" is drawn from. */
export function useTrajectory(candidate: string | null) {
  return useQuery({
    queryKey: m04Keys.trajectory(candidate ?? ""),
    enabled: Boolean(candidate),
    queryFn: () => api.get<TrajectoryResponse>(`/v1/candidates/${candidate}/trajectory`),
  });
}
