"use client";

import { ApiError } from "@/lib/api";
import type {
  Agent,
  AgentKind,
  BudgetPeriod,
  GetOrderResponse,
  Mandate,
  Order,
  OrderApprovalRequest,
} from "@/lib/types";

export type OrderView = "all" | "needs_approval" | "paid" | "blocked" | "in_progress";

export interface Summary {
  currency: string;
  month: { orders: number; paid: number; blocked: number; spent: string };
  needs_approval: number;
  agents_active: number;
  rules_active: number;
  requests: number;
  payment_connected: boolean;
  recent_orders: Order[];
}

export interface AgentRunView {
  id: string;
  status: "running" | "ordered" | "failed";
  summary: string | null;
  errors: string[];
  order_id: string | null;
  order_status: Order["status"] | null;
  pay_url: string | null;
  started_at: string;
  finished_at: string | null;
}

export type MyAgent = Agent & { managed: boolean; kind: AgentKind };

export interface ChatProduct {
  product_id: string;
  title: string;
  brand: string | null;
  price: string;
  currency: string;
  merchant: string;
  category: string;
  category_title: string | null;
  image: string | null;
  url: string | null;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  products: ChatProduct[];
  created_at: string;
  run: AgentRunView | null;
}

export interface ChatSummary {
  id: string;
  title: string;
  agent_id: string;
  updated_at: string;
  preview: string;
}

export interface ChatRule {
  id: string;
  categories: string[];
  merchants: string[];
  budget: string;
  remaining: string;
  period: "week" | "month" | "once";
  currency: string;
}

export type CartLine = ChatProduct & { qty: number };

export interface Cart {
  items: CartLine[];
  total: string;
  count: number;
  currency: string;
  stores: number;
  issues: string[];
}

export interface ChatThread {
  id: string;
  title: string;
  agent: { id: string; name: string; kind: AgentKind; managed: boolean; active: boolean } | null;
  /** The rule this chat shops under; null means all of the agent's active rules. */
  rule_id: string | null;
  rule_options: ChatRule[];
  rules: ChatRule[];
  messages: ChatMessage[];
  cart: Cart;
}

export interface PurchaseRequest {
  id: string;
  agent_id: string;
  agent_name: string | null;
  request_text: string;
  signed_at: string;
  signature: string;
  orders: number;
  agent_managed: boolean;
  run: AgentRunView | null;
}

export interface RuleInput {
  agent_id: string;
  categories: string[];
  merchants: string[];
  budget_amount: string;
  budget_period: BudgetPeriod;
  currency: string;
  expires_at?: string | null;
}

async function call<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api/me/${path}`, {
      method,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, "network_error", "Network error. Check your connection.");
  }
  const data = (await res.json().catch(() => ({}))) as Record<string, unknown>;
  if (res.status === 401) {
    // Session ended: a full load lets the proxy route to sign-in with a clean client state.
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.assign(`/login?next=${encodeURIComponent(window.location.pathname)}`);
  }
  if (!res.ok) {
    const reason = typeof data.reason === "string" ? data.reason : "Something went wrong.";
    throw new ApiError(res.status, typeof data.error === "string" ? data.error : "http_error", reason);
  }
  return (Array.isArray(data.__list) ? data.__list : data) as T;
}

const id = encodeURIComponent;

export const me = {
  summary: () => call<Summary>("summary"),
  orders: (view: OrderView = "all") => call<Order[]>(`orders?view=${view}`),
  order: (orderId: string) => call<GetOrderResponse>(`orders/${id(orderId)}`),
  approve: (orderId: string, req: OrderApprovalRequest) => call<Order>(`orders/${id(orderId)}/approval`, "POST", req),
  agents: () => call<MyAgent[]>("agents"),
  connectAgent: (b: { name: string; public_key: string; device_id?: string }) => call<MyAgent>("agents", "POST", b),
  revokeAgent: (agentId: string) => call<MyAgent>(`agents/${id(agentId)}/revoke`, "POST"),
  rules: () => call<Mandate[]>("mandates"),
  createRule: (b: RuleInput) => call<Mandate>("mandates", "POST", b),
  updateRule: (ruleId: string, b: Partial<RuleInput>) => call<Mandate>(`mandates/${id(ruleId)}`, "PATCH", b),
  endRule: (ruleId: string) => call<Mandate>(`mandates/${id(ruleId)}/revoke`, "POST"),
  requests: () => call<PurchaseRequest[]>("requests"),
  createRequest: (b: { agent_id: string; request_text: string }) => call<PurchaseRequest>("requests", "POST", b),
  runRequest: (requestId: string) => call<AgentRunView>(`requests/${id(requestId)}/run`, "POST"),
  chats: () => call<ChatSummary[]>("chats"),
  createChat: (agentId?: string, ruleId?: string, agentKind?: AgentKind) =>
    call<ChatSummary>("chats", "POST", {
      ...(agentId && { agent_id: agentId }),
      ...(ruleId && { mandate_id: ruleId }),
      ...(agentKind && { agent_kind: agentKind }),
    }),
  chat: (chatId: string) => call<ChatThread>(`chats/${id(chatId)}`),
  setChatRule: (chatId: string, ruleId: string | null) => call<ChatThread>(`chats/${id(chatId)}`, "PATCH", { mandate_id: ruleId }),
  deleteChat: (chatId: string) => call<{ ok: boolean }>(`chats/${id(chatId)}`, "DELETE"),
  send: (chatId: string, content: string) =>
    call<{ messages: ChatMessage[]; title: string }>(`chats/${id(chatId)}/messages`, "POST", { content }),
  addToCart: (chatId: string, b: { message_id: string; product_id: string; qty?: number }) =>
    call<Cart>(`chats/${id(chatId)}/cart`, "POST", b),
  setCartQty: (chatId: string, productId: string, qty: number) =>
    call<Cart>(`chats/${id(chatId)}/cart/${id(productId)}`, "PATCH", { qty }),
  checkout: (chatId: string) => call<{ messages: ChatMessage[]; cart: Cart }>(`chats/${id(chatId)}/checkout`, "POST"),
  payment: () => call<{ connected: boolean }>("payment"),
  paymentSetup: () => call<{ approve_url: string }>("payment/setup", "POST"),
};
