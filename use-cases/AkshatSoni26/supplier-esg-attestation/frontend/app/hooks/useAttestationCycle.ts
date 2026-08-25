"use client";

import { useState, useEffect, useCallback } from "react";
import { Supplier, AttestationCycle, Assessment } from "../types";
import { api } from "../services/api";
import { config } from "../config";

export function useAttestationCycle(cycleYear: number = config.app.defaultCycleYear) {
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [cycles, setCycles] = useState<AttestationCycle[]>([]);
  const [assessmentsMap, setAssessmentsMap] = useState<Record<string, Assessment>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedTier, setSelectedTier] = useState<string>("ALL");

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [supData, cycleData] = await Promise.all([
        api.getSuppliers(),
        api.getCycles(cycleYear),
      ]);

      setSuppliers(supData);
      setCycles(cycleData);

      const assMap: Record<string, Assessment> = {};
      for (const c of cycleData) {
        const ass = await api.getAssessmentByAttestation(c.id);
        if (ass) {
          assMap[c.id] = ass;
        }
      }
      setAssessmentsMap(assMap);
    } catch (err: any) {
      console.error("Failed to load attestation cycle data", err);
      setError(`Backend is not connected at ${config.api.baseUrl}. Please ensure the server is running.`);
    } finally {
      setLoading(false);
    }
  }, [cycleYear]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const filteredSuppliers = suppliers.filter((s) => {
    if (selectedTier === "ALL") return true;
    return s.tier === selectedTier;
  });

  const getCycleForSupplier = (supplierId: string) => {
    return cycles.find((c) => c.supplier_id === supplierId);
  };

  const getAssessmentForSupplier = (supplierId: string) => {
    const cycle = getCycleForSupplier(supplierId);
    return cycle ? assessmentsMap[cycle.id] : null;
  };

  return {
    suppliers,
    cycles,
    assessmentsMap,
    filteredSuppliers,
    loading,
    error,
    selectedTier,
    setSelectedTier,
    refresh: loadData,
    getCycleForSupplier,
    getAssessmentForSupplier,
  };
}
