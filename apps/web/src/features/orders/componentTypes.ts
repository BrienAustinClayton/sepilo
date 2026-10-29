import React from "react";
import { OrderStatusEnum } from "./enums";
import { CartItemDetails, OrderSummary, PreflightSummary, SecurityCheckRecord, ShippingAddress } from "./types";

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

export interface SecurityChecksPanelProps {
  summary: PreflightSummary | null;
  status: OrderStatusEnum;
}

export interface OrderStatusHeroProps {
  order: OrderSummary;
  preflight: PreflightSummary | null;
  children?: React.ReactNode;
}

export interface ShippingAddressCardProps {
  address: ShippingAddress;
}
