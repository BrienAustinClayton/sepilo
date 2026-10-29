import { AgentKind } from "@/lib/types";
import { TONE } from "@/features/orders/utils";

type AgentKindBadge = { label: string; style: string };

const AGENT_KIND_BADGE: Record<AgentKind, AgentKindBadge> = {
  channel3: { label: "Catalog", style: TONE.brand },
  custom: { label: "Your agent", style: "bg-neutral-500/10 text-neutral-400 border border-neutral-500/20" },
};

export function agentKindBadge(kind: string): AgentKindBadge {
  return kind in AGENT_KIND_BADGE ? AGENT_KIND_BADGE[kind as AgentKind] : AGENT_KIND_BADGE.custom;
}
