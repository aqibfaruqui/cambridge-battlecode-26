"use client";

import { ReplayProvider } from "@/contexts/replay-context";

export function Providers({ children }: { children: React.ReactNode }) {
  return <ReplayProvider>{children}</ReplayProvider>;
}
