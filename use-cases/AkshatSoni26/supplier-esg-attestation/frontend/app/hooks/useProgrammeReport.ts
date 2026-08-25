"use client";

import { useState, useEffect, useCallback } from "react";
import { ProgrammeReport } from "../types";
import { api } from "../services/api";
import { config, buildApiUrl } from "../config";

export function useProgrammeReport(cycleYear: number = config.app.defaultCycleYear) {
  const [report, setReport] = useState<ProgrammeReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadReport = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getProgrammeReport(cycleYear);
      setReport(data);
    } catch (err: any) {
      console.error("Failed to load programme report", err);
      setError(err?.message || "Failed to fetch programme report");
    } finally {
      setLoading(false);
    }
  }, [cycleYear]);

  useEffect(() => {
    loadReport();
  }, [loadReport]);

  const pdfDownloadUrl = buildApiUrl(
    config.api.endpoints.downloadDocument(`executive_programme_report_${cycleYear}`, "pdf")
  );

  return {
    report,
    loading,
    error,
    refresh: loadReport,
    pdfDownloadUrl,
  };
}
