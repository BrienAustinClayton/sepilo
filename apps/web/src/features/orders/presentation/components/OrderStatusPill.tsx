"use client";

import React from "react";
import { Ban, CircleCheck, CircleX, Hourglass, ShieldAlert, Undo2, Wallet, LucideIcon } from "lucide-react";
import { OrderStatusEnum } from "../../enums";
import { orderStatusTag } from "../../utils";

const STATUS_ICON: Partial<Record<OrderStatusEnum, LucideIcon>> = {
  [OrderStatusEnum.Captured]: CircleCheck,
  [OrderStatusEnum.PendingApproval]: ShieldAlert,
  [OrderStatusEnum.Voided]: Ban,
  [OrderStatusEnum.Rejected]: Ban,
  [OrderStatusEnum.Failed]: CircleX,
  [OrderStatusEnum.AwaitingPayment]: Wallet,
  [OrderStatusEnum.Refunded]: Undo2,
};

export function OrderStatusIcon({ status, className }: { status: OrderStatusEnum; className?: string }) {
  const Icon = STATUS_ICON[status] ?? Hourglass;
  return <Icon className={className} strokeWidth={2} aria-hidden="true" />;
}

export function OrderStatusPill({ status }: { status: OrderStatusEnum }) {
  const { label, style } = orderStatusTag(status);
  return (
    <span className={`inline-flex items-center gap-1 whitespace-nowrap px-2 py-0.5 rounded-full text-xs font-medium ${style}`}>
      <OrderStatusIcon status={status} className="w-3.5 h-3.5" />
      {label}
    </span>
  );
}
