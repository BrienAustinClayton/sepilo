import {
  ApprovalDecisionEnum,
  OrderStatusEnum,
  PreflightStatusEnum,
  SecurityCheckResultEnum,
  SecurityCheckStepEnum,
} from "./enums";

export interface CartItemDetails {
  product_id: string;
  title: string;
  unit_price?: string;
  qty: number;
  category?: string;
}

export interface SecurityCheckRecord {
  step: SecurityCheckStepEnum;
  result: SecurityCheckResultEnum;
  latency_ms: number;
  timestamp: string;
  details: Record<string, unknown> | null;
}

export interface PreflightItem {
  id: string;
  label: string;
  status: PreflightStatusEnum;
  detail: string;
}

export interface PreflightSummary {
  items: PreflightItem[];
  passed: number;
  total: number;
}

export interface ChecksSummary {
  passed: number;
  total: number;
  failed: string[];
}

export interface OrderCounts {
  all: number;
  needs_approval: number;
  paid: number;
  blocked: number;
  in_progress: number;
}

export interface ShippingAddress {
  name?: string;
  line1?: string;
  line2?: string;
  city?: string;
  region?: string;
  state?: string;
  postal_code?: string;
  country?: string;
}

export interface OrderApprovalRecord {
  id: string;
  decision: ApprovalDecisionEnum;
  decided_at: string;
  reason: string | null;
}

export interface OrderSummary {
  id: string;
  merchant: string;
  total: string;
  currency: string;
  status: OrderStatusEnum;
  created_at: string;
  cart: CartItemDetails[] | null;
  approval_timeout_at: string | null;
  decision_reasons: string[] | null;
  pay_url?: string | null;
  shipping_address?: ShippingAddress | null;
  checks?: ChecksSummary | null;
}

export interface OrderDetailResponse {
  order: OrderSummary;
  checks: SecurityCheckRecord[];
  approval: OrderApprovalRecord | null;
  proof_bundle: string | null;
  paypal_approve_url: string | null;
}
