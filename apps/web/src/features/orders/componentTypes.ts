import { CartItemDetails, OrderSummary, PreflightSummary, SecurityCheckRecord } from "./types";

export interface OrdersListProps {
  orders: OrderSummary[];
}

export interface OrderHeaderProps {
  order: OrderSummary;
}

export interface SecurityTimelineProps {
  checks: SecurityCheckRecord[];
}

export interface CartItemsTableProps {
  items: CartItemDetails[];
  currency: string;
}

export interface OrderApprovalActionsProps {
  orderId: string;
  timeoutAt: string | null;
  total: string;
  onApprove: (confirmTotal?: string) => void;
  onDecline: () => void;
  isProcessing: boolean;
}

export interface PreflightChecklistProps {
  summary: PreflightSummary;
}
