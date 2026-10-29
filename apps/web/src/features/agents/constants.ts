import { AgentKind } from "@/lib/types";
import { TONE } from "@/features/orders/utils";

export const AGENT_KIND_BADGE: Record<AgentKind, { label: string; style: string }> = {
  channel3: { label: "Catalog", style: TONE.brand },
  deals: { label: "Web deals", style: TONE.success },
  custom: { label: "Your agent", style: "bg-neutral-500/10 text-neutral-400 border border-neutral-500/20" },
};
