"use client";

import React from "react";
import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { formatCurrency, formatRelativeTime } from "@/features/orders/utils";
import { MyDisputesListProps } from "../../componentTypes";
import { REASON_LABELS } from "../../constants";
import { shortOrderId } from "../../utils";
import { DisputeStatusTag } from "./DisputeTags";

export function MyDisputesList({ disputes }: MyDisputesListProps) {
  return (
    <ul className="divide-y divide-line">
      {disputes.map((dispute) => (
        <li key={dispute.id}>
          <Link href={`/disputes/${dispute.id}`} className="flex items-start gap-3 px-4 py-3.5 hover:bg-fg/3 transition">
            <div className="min-w-0 flex-1 space-y-1">
              <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
                <span className="text-sm font-medium text-fg">Order {shortOrderId(dispute.order_id)}</span>
                <DisputeStatusTag status={dispute.status} />
              </div>
              <div className="text-xs text-fg-muted">
                {REASON_LABELS[dispute.reason] ?? dispute.reason}
                {dispute.order && ` · ${formatCurrency(dispute.order.total, dispute.order.currency)} at ${dispute.order.merchant}`}
                {` · ${formatRelativeTime(dispute.created_at)}`}
              </div>
              {dispute.decision_note && (
                <p className="text-xs text-fg-2 line-clamp-2">Our reply: {dispute.decision_note}</p>
              )}
            </div>
            <ChevronRight className="w-4 h-4 mt-1 shrink-0 text-fg-dim" strokeWidth={1.8} />
          </Link>
        </li>
      ))}
    </ul>
  );
}
