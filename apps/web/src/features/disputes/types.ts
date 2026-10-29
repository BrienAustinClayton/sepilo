import {
  DisputeAiSourceEnum,
  DisputeDecisionEnum,
  DisputePriorityEnum,
  DisputeReasonEnum,
  DisputeStatusEnum,
  DisputeSuggestionEnum,
} from "./enums";

export interface DisputeOrderRef {
  merchant: string;
  total: string;
  currency: string;
}

export interface Dispute {
  id: string;
  order_id: string;
  reason: DisputeReasonEnum;
  description: string;
  status: DisputeStatusEnum;
  decision_note: string | null;
  refund_id: string | null;
  created_at: string;
  decided_at: string | null;
  order: DisputeOrderRef | null;
}

export interface ManagerDispute extends Dispute {
  user_email: string | null;
  priority: number;
  priority_label: DisputePriorityEnum;
  suggestion: DisputeSuggestionEnum | null;
  ai_reasons: string[];
  ai_source: DisputeAiSourceEnum | null;
  decided_by: string | null;
}

export interface DisputeCartLine {
  product_id: string;
  title?: string;
  qty: number;
  category?: string;
  unit_price?: string;
  price?: string;
}

export interface DisputeOrderDetail {
  id: string;
  merchant: string;
  cart: DisputeCartLine[] | null;
  total: string;
  currency: string;
  status: string;
  created_at: string;
}

export interface DisputeCheckResult {
  step: string;
  result: string;
  score: number | null;
}

export interface DisputeUserHistory {
  total: number;
  refunded_90d: number;
  open: number;
}

export interface ManagerDisputeDetail extends ManagerDispute {
  order_detail: DisputeOrderDetail;
  checks: DisputeCheckResult[];
  user_history: DisputeUserHistory;
}

export interface CreateDisputePayload {
  reason: DisputeReasonEnum;
  description: string;
}

export interface DecideDisputePayload {
  decision: DisputeDecisionEnum;
  note: string;
  confirm_total?: string;
}

export interface DecideDisputeVariables {
  disputeId: string;
  payload: DecideDisputePayload;
}
