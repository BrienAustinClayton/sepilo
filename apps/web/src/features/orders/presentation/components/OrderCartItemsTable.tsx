"use client";

import React from "react";
import { CartItemsTableProps } from "../../componentTypes";
import { CartItemDetails } from "../../types";
import { calculateLineTotal, formatCurrency } from "../../utils";

export function OrderCartItemsTable({ items, currency }: CartItemsTableProps) {
  const hasNoItems = items.length === 0;

  if (hasNoItems) {
    return (
      <div className="p-6 text-center text-sm text-fg-muted">
        No cart items recorded for this order.
      </div>
    );
  }

  return (
    <>
      <ul className="sm:hidden divide-y divide-line">
        {items.map((item: CartItemDetails) => {
          const unitPrice = item.unit_price ?? "0.00";
          return (
            <li key={item.product_id} className="flex items-start justify-between gap-3 px-4 py-3">
              <div className="min-w-0">
                <div className="text-sm font-medium text-fg-2 line-clamp-2">{item.title}</div>
                <div className="text-xs text-fg-muted">{item.category}</div>
              </div>
              <div className="shrink-0 text-right">
                <div className="text-sm font-semibold tabular-nums text-fg">
                  {formatCurrency(calculateLineTotal(unitPrice, item.qty), currency)}
                </div>
                <div className="text-xs tabular-nums text-fg-dim">
                  {item.qty} × {formatCurrency(unitPrice, currency)}
                </div>
              </div>
            </li>
          );
        })}
      </ul>
    <div className="hidden sm:block overflow-x-auto">
      <table className="w-full border-collapse">
        <thead className="border-b border-line bg-fg/2">
          <tr>
            <th className="px-4 py-2.5 text-left text-xs font-medium text-fg-dim">Item</th>
            <th className="px-4 py-2.5 text-right text-xs font-medium text-fg-dim">Unit Price</th>
            <th className="px-4 py-2.5 text-right text-xs font-medium text-fg-dim">Qty</th>
            <th className="px-4 py-2.5 text-right text-xs font-medium text-fg-dim">Total</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item: CartItemDetails) => {
            const unitPrice = item.unit_price ?? "0.00";
            const lineTotal = calculateLineTotal(unitPrice, item.qty);

            return (
              <tr key={item.product_id} className="border-b border-line last:border-0">
                <td className="px-4 py-3 text-sm text-fg-2 align-middle font-medium">
                  <div>{item.title}</div>
                  <div className="text-xs text-fg-muted font-normal">{item.category}</div>
                </td>
                <td className="px-4 py-3 text-sm text-right tabular-nums text-fg-2 align-middle">
                  {formatCurrency(unitPrice, currency)}
                </td>
                <td className="px-4 py-3 text-sm text-right tabular-nums text-fg-2 align-middle">
                  {item.qty}
                </td>
                <td className="px-4 py-3 text-sm text-right tabular-nums font-semibold text-fg align-middle">
                  {formatCurrency(lineTotal, currency)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
    </>
  );
}
