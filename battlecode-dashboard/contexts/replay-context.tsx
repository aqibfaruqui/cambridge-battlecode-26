"use client";

import type { MatchMetrics, ParsedReplay } from "@/types/game";
import { computeMatchMetrics } from "@/lib/analysis-engine";
import React, {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
} from "react";

interface ReplayContextValue {
  replay: ParsedReplay | null;
  metrics: MatchMetrics | null;
  setReplay: (r: ParsedReplay | null) => void;
  clearReplay: () => void;
}

const ReplayContext = createContext<ReplayContextValue | null>(null);

export function ReplayProvider({ children }: { children: React.ReactNode }) {
  const [replay, setReplayState] = useState<ParsedReplay | null>(null);

  const metrics = useMemo(() => {
    if (!replay) return null;
    try {
      return computeMatchMetrics(replay);
    } catch (e) {
      console.error(e);
      return null;
    }
  }, [replay]);

  const setReplay = useCallback((r: ParsedReplay | null) => {
    setReplayState(r);
  }, []);

  const clearReplay = useCallback(() => setReplayState(null), []);

  const value = useMemo(
    () => ({ replay, metrics, setReplay, clearReplay }),
    [replay, metrics, setReplay, clearReplay],
  );

  return <ReplayContext.Provider value={value}>{children}</ReplayContext.Provider>;
}

export function useReplay() {
  const ctx = useContext(ReplayContext);
  if (!ctx) {
    throw new Error("useReplay must be used within ReplayProvider");
  }
  return ctx;
}
