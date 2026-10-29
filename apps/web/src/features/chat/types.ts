import { AgentRunStatusEnum, ChatRoleEnum, CartCheckStatusEnum, CartReviewDecisionEnum } from "./enums";

export interface ChatProductItem {
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
  compare_price?: string | null;
  store_count?: number | null;
}

export interface AgentRunInfo {
  id: string;
  status: AgentRunStatusEnum;
  summary: string | null;
  errors: string[];
  order_id: string | null;
  order_status: string | null;
  pay_url: string | null;
  started_at: string;
  finished_at: string | null;
}

export interface ChatMessageItem {
  id: string;
  role: ChatRoleEnum;
  content: string;
  products: ChatProductItem[];
  created_at: string;
  run: AgentRunInfo | null;
}

export interface ChatRuleOption {
  id: string;
  agent_id?: string;
  categories: string[];
  merchants: string[];
  budget: string;
  remaining: string;
  period: string;
  currency: string;
}

export interface CartItemLine extends ChatProductItem {
  qty: number;
}

export interface CartCheckItem {
  key: string;
  label: string;
  status: CartCheckStatusEnum;
  detail: string;
}

export interface CartReview {
  decision: CartReviewDecisionEnum;
  checks: CartCheckItem[];
}

export interface ChatCartState {
  items: CartItemLine[];
  total: string;
  count: number;
  currency: string;
  stores: number;
  issues: string[];
}
