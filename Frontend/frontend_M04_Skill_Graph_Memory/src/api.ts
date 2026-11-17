/**
 * M04 over `@ai/core`'s fetch wrapper, which carries the session's identity.
 * Every route here is the student's own record; the backend refuses anybody
 * else (Platform_Core's candidate guard), and these hooks render its sentence.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, sessionHeaders } from "@ai/core";

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

/* ------------------------------------------------------------------ */
/*  The student's picture (2026-11-17)                                */
/* ------------------------------------------------------------------ */

/**
 * The picture as a blob URL, fetched with identity — an `<img src>` cannot
 * send the headers every candidate route needs. Keyed on the profile's
 * `photo` digest, so a new picture is fetched the moment it changes and the
 * old one never is again. `null` when there is no picture: every screen then
 * shows what it showed before.
 */
export function useProfilePhoto(candidate: string | null, digest: string | null | undefined) {
  return useQuery({
    queryKey: ["m04", "photo", candidate ?? "", digest ?? ""],
    enabled: Boolean(candidate && digest),
    staleTime: Infinity,
    gcTime: Infinity,
    retry: false,
    queryFn: async () => {
      const response = await fetch(`/v1/candidates/${candidate}/photo`, { headers: sessionHeaders() });
      if (response.status === 404) return null;
      if (!response.ok) throw new Error(`The picture could not be loaded (${response.status}).`);
      return URL.createObjectURL(await response.blob());
    },
  });
}

/** Store the picture (already square and small: see `squarePhoto`). */
export function useSetPhoto(candidate: string | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (photo: Blob) => {
      const response = await fetch(`/v1/candidates/${candidate}/photo`, {
        method: "PUT",
        headers: { ...sessionHeaders(), "Content-Type": photo.type || "image/jpeg" },
        body: photo,
      });
      if (!response.ok) {
        let detail = `The picture could not be saved (${response.status}).`;
        try {
          const body = await response.json();
          if (typeof body?.detail === "string") detail = body.detail;
        } catch {
          /* keep the sentence above */
        }
        throw new Error(detail);
      }
      return (await response.json()) as { sha256: string };
    },
    onSuccess: () => client.invalidateQueries({ queryKey: m04Keys.profile(candidate ?? "") }),
  });
}

export function useRemovePhoto(candidate: string | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api.del<void>(`/v1/candidates/${candidate}/photo`),
    onSuccess: () => client.invalidateQueries({ queryKey: m04Keys.profile(candidate ?? "") }),
  });
}

/**
 * Any picture the browser can open, made square (centre crop) and 512 px,
 * as a JPEG of about 50 KB. Done here rather than on the server: the server
 * then stores exactly what every screen shows, and never decodes an upload.
 */
export async function squarePhoto(file: File, size = 512): Promise<Blob> {
  if (!file.type.startsWith("image/")) throw new Error("Choose a picture file (JPEG, PNG or similar).");
  const url = URL.createObjectURL(file);
  try {
    const image = await new Promise<HTMLImageElement>((resolve, reject) => {
      const el = new Image();
      el.onload = () => resolve(el);
      el.onerror = () => reject(new Error("That file could not be opened as a picture."));
      el.src = url;
    });
    const side = Math.min(image.naturalWidth, image.naturalHeight);
    if (side < 64) throw new Error("That picture is too small to show clearly.");
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = Math.min(size, side);
    const context = canvas.getContext("2d");
    if (!context) throw new Error("This browser cannot prepare the picture.");
    context.drawImage(
      image,
      (image.naturalWidth - side) / 2,
      (image.naturalHeight - side) / 2,
      side,
      side,
      0,
      0,
      canvas.width,
      canvas.height,
    );
    return await new Promise<Blob>((resolve, reject) =>
      canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("The picture could not be prepared."))), "image/jpeg", 0.88),
    );
  } finally {
    URL.revokeObjectURL(url);
  }
}
