"use client";

import React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { OrdersListProps } from "../../componentTypes";
import { OrderSummary } from "../../types";
import { describeItems, formatAbsoluteTime, formatCurrency, formatRelativeTime } from "../../utils";
import { ChecksBadge } from "./ChecksBadge";
import { OrderStatusPill } from "./OrderStatusPill";

const HEAD = "px-4 py-2.5 text-xs font-medium text-fg-dim whitespace-nowrap";

export function OrdersTableDesktop({ orders }: OrdersListProps) {
  const router = useRouter();

  return (
    <div className="hidden sm:block overflow-x-auto">
      <table className="w-full border-collapse">
        <thead className="border-b border-line bg-fg/2">
          <tr>
            <th scope="col" className={`${HEAD} text-left`}>Items</th>
            <th scope="col" className={`${HEAD} text-right`}>Total</th>
            <th scope="col" className={`${HEAD} text-left`}>Status</th>
            <th scope="col" className={`${HEAD} text-left`}>Checks</th>
            <th scope="col" className={`${HEAD} text-left`}>Created</th>
          </tr>
        </thead>
        <tbody>
          {orders.map((order: OrderSummary) => (
            <tr
              key={order.id}
              onClick={() => router.push(`/orders/${order.id}`)}
              className="cursor-pointer border-b border-line last:border-0 transition hover:bg-fg/4 focus-within:bg-fg/4"
            >
              <td className="px-4 py-3 align-middle max-w-80">
                <Link
                  href={`/orders/${order.id}`}
                  onClick={(event) => event.stopPropagation()}
                  className="block truncate text-sm font-medium text-fg hover:text-blue-400"
                >
                  {describeItems(order)}
                </Link>
                <div className="mt-0.5 truncate text-xs text-fg-dim">{order.merchant}</div>
              </td>
              <td className="px-4 py-3 text-sm text-right tabular-nums text-fg align-middle font-medium">
                {formatCurrency(order.total, order.currency)}
              </td>
              <td className="px-4 py-3 align-middle">
                <OrderStatusPill status={order.status} />
              </td>
              <td className="px-4 py-3 align-middle">
                <ChecksBadge checks={order.checks} />
              </td>
              <td className="px-4 py-3 text-sm text-fg-dim whitespace-nowrap align-middle">
                <time dateTime={order.created_at} title={formatAbsoluteTime(order.created_at)}>
                  {formatRelativeTime(order.created_at)}
                </time>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
