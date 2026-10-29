import { OrderApprovalRecord, OrderDetailResponse, OrderSummary, SecurityCheckRecord } from "./types";

export interface ApiOrderDetail extends Omit<OrderSummary, "approval_timeout_at" | "decision_reasons" | "checks"> {
  reasons?: string[] | null;
  pay_url?: string | null;
  approval?: (Omit<OrderApprovalRecord, "reason"> & { expires_at: string | null }) | null;
  checks?: (Omit<SecurityCheckRecord, "latency_ms" | "timestamp"> & { duration_ms?: number; created_at?: string })[];
}

export function toOrderDetail(raw: ApiOrderDetail): OrderDetailResponse {
  const { checks, approval, reasons, ...order } = raw;
  return {
    order: {
      ...order,
      approval_timeout_at: approval?.expires_at ?? null,
      decision_reasons: Array.isArray(reasons) ? reasons : null,
      pay_url: raw.pay_url ?? null,
    },
    checks: (Array.isArray(checks) ? checks : []).map((c) => ({
      step: c.step,
      result: c.result,
      details: c.details ?? null,
      latency_ms: c.duration_ms ?? 0,
      timestamp: c.created_at ?? "",
    })),
    approval: approval ? { id: approval.id, decision: approval.decision, decided_at: approval.decided_at, reason: null } : null,
    proof_bundle: null,
    paypal_approve_url: raw.pay_url ?? null,
  };
}
