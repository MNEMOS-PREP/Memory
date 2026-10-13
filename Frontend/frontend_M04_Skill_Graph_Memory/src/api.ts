/**
 * M04 over `@ai/core`'s fetch wrapper, which carries the session's identity.
 * Every route here is the student's own record; the backend refuses anybody
 * else (Platform_Core's candidate guard), and these hooks render its sentence.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@ai/core";

import type {
  BottlenecksResponse,
  ConceptDetail,
  ConsentRecord,
  Curriculum,
  CurriculumSummary,
  EvidenceResponse,
  MasteryResponse,
  ProfileUpdate,
  StudentProfile,
  TrajectoryResponse,
} from "./types";

export const m04Keys = {
  mastery: (candidate: string) => ["m04", "mastery", candidate] as const,
  bottlenecks: (candidate: string) => ["m04", "bottlenecks", candidate] as const,
  evidence: (candidate: string, concept: string) =>
    ["m04", "evidence", candidate, concept] as const,
  trajectory: (candidate: string) => ["m04", "trajectory", candidate] as const,
  concept: (id: string) => ["m04", "concept", id] as const,
  consent: (candidate: string) => ["m04", "consent", candidate] as const,
  profile: (candidate: string) => ["m04", "profile", candidate] as const,
  curricula: () => ["m04", "curricula"] as const,
  curriculum: (id: string) => ["m04", "curriculum", id] as const,
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

/** One concept from the ontology, with what it builds on and what it unlocks. */
export function useConcept(id: string | null) {
  return useQuery({
    queryKey: m04Keys.concept(id ?? ""),
    enabled: Boolean(id),
    queryFn: () => api.get<ConceptDetail>(`/v1/concepts/${encodeURIComponent(id ?? "")}`),
    staleTime: Infinity,
  });
}

/** The practice consent, or null when there is none. Without it no
 *  interview can move the skill graph (FR-4.20), so the shell asks first. */
export function usePracticeConsent(candidate: string | null) {
  return useQuery({
    queryKey: m04Keys.consent(candidate ?? ""),
    enabled: Boolean(candidate),
    queryFn: async () => {
      const rows = await api.get<ConsentRecord[]>(
        `/v1/candidates/${candidate}/consent?purpose=practice`,
      );
      return rows.find((r) => r.active) ?? null;
    },
  });
}

export function useGrantConsent(candidate: string | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      api.post<ConsentRecord>(`/v1/candidates/${candidate}/consent`, {
        purpose: "practice",
        policy_version: "1.0",
      }),
    onSuccess: (record) => client.setQueryData(m04Keys.consent(candidate ?? ""), record),
  });
}

export function useProfile(candidate: string | null) {
  return useQuery({
    queryKey: m04Keys.profile(candidate ?? ""),
    enabled: Boolean(candidate),
    queryFn: () => api.get<StudentProfile>(`/v1/candidates/${candidate}/profile`),
  });
}

export function useSaveProfile(candidate: string | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (update: ProfileUpdate) =>
      api.put<StudentProfile>(`/v1/candidates/${candidate}/profile`, update),
    onSuccess: (profile) => client.setQueryData(m04Keys.profile(candidate ?? ""), profile),
  });
}

/** The programmes a student can pick at sign-in. Changes only when the college
 *  publishes a curriculum, so it is fetched once per visit. */
export function useCurricula() {
  return useQuery({
    queryKey: m04Keys.curricula(),
    queryFn: () => api.get<CurriculumSummary[]>("/v1/curricula"),
    staleTime: Infinity,
  });
}

/** One programme: its semesters, elective baskets, and what each course teaches. */
export function useCurriculum(id: string | null | undefined) {
  return useQuery({
    queryKey: m04Keys.curriculum(id ?? ""),
    enabled: Boolean(id),
    queryFn: () => api.get<Curriculum>(`/v1/curricula/${encodeURIComponent(id ?? "")}`),
    staleTime: Infinity,
  });
}

/** FR-4.18a: every row M04 holds about the student, as a file they keep. */
export async function downloadMyData(candidate: string): Promise<void> {
  const body = await api.get<unknown>(`/v1/candidates/${candidate}/export`);
  const blob = new Blob([JSON.stringify(body, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `my-skill-graph-${new Date().toISOString().slice(0, 10)}.json`;
  link.click();
  URL.revokeObjectURL(url);
}

/** FR-4.18b: the hard delete. Consent rows stay, revoked, as the record of
 *  when the student withdrew. */
export function useDeleteMyData(candidate: string | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api.del<Record<string, unknown>>(`/v1/candidates/${candidate}/memory`),
    onSuccess: () => client.invalidateQueries({ queryKey: ["m04"] }),
  });
}
