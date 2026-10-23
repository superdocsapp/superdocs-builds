import { useMutation, useQuery } from "@tanstack/react-query";

import { createBrief, getBrief, getBriefStatus, uploadDocuments } from "@/services/api";

export function useUploadDocuments() {
  return useMutation({
    mutationFn: (form: FormData) => uploadDocuments(form),
  });
}

export function useCreateBrief() {
  return useMutation({
    mutationFn: (sessionId: string) => createBrief(sessionId),
  });
}

export function useBrief(briefId?: string) {
  return useQuery({
    queryKey: ["brief", briefId],
    queryFn: () => getBrief(briefId!),
    enabled: Boolean(briefId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (!status || status === "completed" || status === "failed") return false;
      return 2500;
    },
  });
}

export function useBriefStatus(briefId?: string, enabled = true) {
  return useQuery({
    queryKey: ["brief-status", briefId],
    queryFn: () => getBriefStatus(briefId!),
    enabled: Boolean(briefId) && enabled,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (!status || status === "completed" || status === "failed") return false;
      return 1500;
    },
  });
}
