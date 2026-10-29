/**
 * IntentLock API types – mirrors CONTRACTS.md exactly.
 * Source of truth: plans/CONTRACTS.md
 */

// ---------------------------------------------------------------------------
// Enums
// ---------------------------------------------------------------------------

export type OrderStatus =
  | "received"
  | "awaiting_payment"
  | "authorized"
  | "checking"
  | "captured"
  | "voided"
  | "rejected"
  | "pending_approval"
  | "failed";

export type Decision = "reject" | "void" | "hold" | "capture";

export type CheckStep =
  | "verify_agent"
  | "check_mandate"
  | "authorize_payment"
  | "scan_injection"
  | "intent_diff"
  | "graph_risk"
  | "decide"
  | "capture_or_void"
  | "build_proof";

export type CheckResult = "pass" | "fail" | "flag" | "error" | "skipped";

export type IntentDiffExplained = "yes" | "no" | "uncertain";

export type IntentDiffIssue =
  | "none"
  | "extra_item"
  | "variant_mismatch"
  | "quantity"
  | "price"
  | "address"
  | "merchant";

export type ScheduleEventType =
  | "mandate_window"
  | "planned_purchase"
  | "order";

export type ScheduleEventStatus =
  | "tentative"
  | "confirmed"
  | "captured"
  | "pending_approval"
  | "voided"
  | "rejected";

export type LabScenario =
  | "normal"
  | "hidden_gift_card"
  | "wrong_variant"
  | "overpriced_merchant"
  | "bot_farm"
  | "revoked_agent";

export type BudgetPeriod = "week" | "month" | "once";

// ---------------------------------------------------------------------------
// Core entities
// ---------------------------------------------------------------------------

export interface User {
  id: string; // usr_
  name: string;
}

export type AgentKind = "channel3" | "deals" | "custom";

export interface Agent {
  id: string; // agt_
  user_id: string;
  name: string;
  public_key: string;
  device_id: string;
  revoked_at: string | null;
  created_at?: string | null;
}

export interface Mandate {
  id: string; // mdt_
  agent_id: string;
  categories: string[];
  merchants: string[];
  /** Decimal string with 2 decimal places, e.g. "50.00". Never use float math. */
  budget_amount: string;
  budget_period: BudgetPeriod;
  currency: string;
  starts_at: string;
  expires_at: string | null;
  /** JSONB object on the server; transmitted as a parsed object. */
  signed_json: Record<string, unknown>;
  signature: string;
  revoked_at: string | null;
}

export interface Intent {
  id: string; // int_
  user_id: string;
  agent_id: string;
  request_text: string;
  signed_at: string;
  signature: string;
}

/** Cart line item – used in checkout requests and order records. */
export interface CartItem {
  product_id: string;
  title: string;
  variant: string;
  qty: number;
  /** Decimal string with 2 decimal places per CONTRACTS, e.g. "9.99". */
  unit_price: string;
  currency: string;
  category: string;
  url: string;
}

export interface Check {
  id: string; // chk_
  order_id: string;
  step: CheckStep;
  result: CheckResult;
  score: number | null;
  details: ScanInjectionDetails | IntentDiffDetails | GraphRiskDetails | null;
  duration_ms: number;
}

export interface Approval {
  id: string; // apr_
  order_id: string;
  /** null until a decision is made */
  decision: "approve" | "decline" | null;
  requested_at: string;
  /** null while pending */
  decided_at: string | null;
  /** 30-min void deadline; null if already decided */
  expires_at: string | null;
}

export interface Order {
  id: string; // ord_
  intent_id: string;
  agent_id: string;
  user_id: string;
  merchant: string;
  cart: CartItem[];
  /** Decimal string with 2 decimal places, e.g. "42.50". */
  total: string;
  currency: string;
  page_urls: string[];
  shipping_address: Record<string, string>;
  trace_id: string;
  status: OrderStatus;
  /** PayPal page where the buyer approves the payment (only while awaiting_payment). */
  pay_url?: string | null;
  decision: Decision | null;
  reasons: string[];
  checks?: Check[];
  approval?: Approval | null;
  created_at: string;
  updated_at?: string;
}

/** Bryntum CrudManager event record for /schedule endpoints. */
export interface ScheduleEvent {
  id: string;
  resourceId: string;
  name: string;
  startDate: string;
  endDate: string;
  type: ScheduleEventType;
  status: ScheduleEventStatus;
  order_id?: string;
}

/** Bryntum CrudManager response shape (simplified). */
export interface ScheduleLoadResponse {
  success: boolean;
  resources: { rows: Array<{ id: string; name: string }> };
  events: { rows: ScheduleEvent[] };
  assignments: { rows: Array<{ id: string; eventId: string; resourceId: string }> };
}

export interface ProofBundle {
  version: 1;
  order: Order;
  intent: Pick<Intent, "id" | "request_text" | "signed_at" | "signature">;
  mandate: Pick<Mandate, "id" | "signed_json" | "signature">;
  cart: CartItem[];
  page_urls: string[];
  checks: Array<{
    step: CheckStep;
    result: CheckResult;
    score: number | null;
    details: unknown;
    duration_ms: number;
  }>;
  decision: Decision;
  approval: Approval | null;
  paypal: {
    order_id: string;
    authorization_id: string;
    capture_id: string | null;
    void: boolean;
  };
  astropods_trace_id: string;
  issued_at: string;
}

// ---------------------------------------------------------------------------
// Check detail shapes
// ---------------------------------------------------------------------------

export interface ScanInjectionDetails {
  detected: boolean;
  confidence: number;
  findings: Array<{
    url: string;
    technique:
      | "hidden_css"
      | "html_comment"
      | "aria_hidden"
      | "offscreen"
      | "zero_font"
      | "white_on_white"
      | "phrase";
    snippet: string;
  }>;
}

export interface IntentDiffDetails {
  items: Array<{
    product_id: string;
    /** Up to 80 chars per CONTRACTS. */
    title: string;
    explained: IntentDiffExplained;
    issue: IntentDiffIssue;
    reason: string;
    source: "deterministic" | "llm";
  }>;
  price_anomaly: boolean;
}

export interface GraphRiskDetails {
  score: number;
  signals: Array<{
    name:
      | "shared_key"
      | "bot_farm"
      | "unfamiliar_device"
      | "out_of_mandate"
      | "flagged_merchant";
    weight: number;
    evidence: string[];
  }>;
}

// ---------------------------------------------------------------------------
// Catalog
// ---------------------------------------------------------------------------

/** A single variant option on a catalog product. */
export interface CatalogProductVariant {
  name: string;
  label: string;
  product_id: string;
}

/** Catalog product – matches data/seed/catalog.json row shape (all fields required). */
export interface CatalogProduct {
  product_id: string;
  merchant: string;
  category: string;
  title: string;
  description: string;
  key_features: string[];
  price: number;
  currency: string;
  image_url: string;
  variants: CatalogProductVariant[];
  offers: Array<{ merchant: string; price: number }>;
}

// ---------------------------------------------------------------------------
// API request / response shapes
// ---------------------------------------------------------------------------

// POST /users
export interface CreateUserRequest {
  name: string;
}
export interface CreateUserResponse {
  id: string;
}

// GET /vault/setup
export interface VaultSetupResponse {
  approve_url: string;
}

// POST /agents
export interface CreateAgentRequest {
  user_id: string;
  name: string;
  public_key: string;
  device_id: string;
}

// POST /mandates
export interface CreateMandateRequest {
  agent_id: string;
  categories: string[];
  merchants: string[];
  /** Decimal string with 2 decimal places, e.g. "200.00". */
  budget_amount: string;
  budget_period: BudgetPeriod;
  currency: string;
  starts_at: string;
  expires_at: string | null;
}

// POST /intents
export interface CreateIntentRequest {
  user_id: string;
  agent_id: string;
  request_text: string;
}
export interface CreateIntentResponse {
  id: string;
  signed_at: string;
  signature: string;
}

// GET /intents/{id}
export type GetIntentResponse = Intent;

// GET /catalog
export type GetCatalogResponse = CatalogProduct[];

// POST /checkout — only the signed agent calls this; no web client method.
export interface CheckoutRequest {
  intent_id: string;
  merchant: string;
  cart: CartItem[];
  page_urls: string[];
  shipping_address: Record<string, string>;
  trace_id: string;
}
export interface CheckoutResponse {
  order_id: string;
  status: OrderStatus;
  decision: Decision;
  reasons: string[];
}

// GET /orders
export type GetOrdersResponse = Order[];

// GET /orders/{id}
export type GetOrderResponse = Order & { checks: Check[]; approval: Approval | null };

// POST /orders/{id}/approval
export interface OrderApprovalRequest {
  decision: "approve" | "decline";
}

// GET /orders/{id}/proof
export interface GetProofResponse {
  bundle: ProofBundle;
  sha256: string;
  signature: string;
  public_key: string;
  valid: boolean;
}

// POST /proofs/verify
export interface VerifyProofRequest {
  bundle: ProofBundle;
  signature: string;
}
export interface VerifyProofResponse {
  valid: boolean;
  sha256: string;
}

// GET /graph/risk/{order_id}
export type GetGraphRiskResponse = GraphRiskDetails;

// POST /graph/ask
export interface GraphAskRequest {
  question: string;
}
export interface GraphAskResponse {
  answer: string;
  facts: string[];
  evidence: string[];
}

// POST /schedule/propose
export interface ScheduleProposeRequest {
  agent_id: string;
  title: string;
  start: string;
  end: string;
}

// POST /lab/{scenario}
export interface LabRunRequest {
  user_id: string;
}
export interface LabRunResponse {
  order_id: string;
  expected_decision: Decision;
  actual_decision: Decision;
  status: OrderStatus;
}

// GET /llm/usage
export interface LlmUsageResponse {
  spent_usd: number;
  remaining_usd: number;
  calls: number;
  fallback_calls: number;
}

// GET /console/metrics
export interface ConsoleMetricsResponse {
  decisions_over_time: Array<{ date: string; decision: Decision; count: number }>;
  risk_histogram: Array<{ bucket: string; count: number }>;
  top_flagged_merchants: Array<{ merchant: string; count: number }>;
  approval_rate: number;
}

// GET /health
export interface HealthResponse {
  ok: boolean;
  version: string;
}

// Agent keys
export interface AgentKeysResponse {
  keys: Array<{
    keyid: string;
    alg: "ed25519";
    public_key: string;
    revoked: boolean;
  }>;
}
