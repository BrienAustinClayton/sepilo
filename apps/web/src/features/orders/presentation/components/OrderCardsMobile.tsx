"use client";

import React from "react";
import Link from "next/link";
import { OrdersListProps } from "../../componentTypes";
import { OrderSummary } from "../../types";
import { describeItems, formatCurrency, formatRelativeTime } from "../../utils";
import { ChecksBadge } from "./ChecksBadge";
import { OrderStatusPill } from "./OrderStatusPill";

export function OrderCardsMobile({ orders }: OrdersListProps) {
  return (
    <ul className="sm:hidden divide-y divide-line">
      {orders.map((order: OrderSummary) => (
        <li key={order.id}>
          <Link
            href={`/orders/${order.id}`}
            className="block min-h-14 px-4 py-3.5 active:bg-fg/4"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="text-sm font-medium text-fg line-clamp-2">{describeItems(order)}</div>
                <div className="mt-0.5 text-xs text-fg-dim truncate">{order.merchant}</div>
              </div>
              <span className="shrink-0 text-sm font-semibold tabular-nums text-fg">
                {formatCurrency(order.total, order.currency)}
              </span>
            </div>
            <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1.5">
              <OrderStatusPill status={order.status} />
              <ChecksBadge checks={order.checks} />
              <span className="ml-auto text-xs text-fg-dim">{formatRelativeTime(order.created_at)}</span>
            </div>
          </Link>
        </li>
      ))}
    </ul>
  );
}
