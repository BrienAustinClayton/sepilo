"use client";

import React from "react";
import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { formatCurrency, formatRelativeTime } from "@/features/orders/utils";
import { ManagerDisputesListProps } from "../../componentTypes";
import { DisputeStatusEnum } from "../../enums";
import { REASON_LABELS } from "../../constants";
import { shortOrderId } from "../../utils";
import {
  DisputeAiSourceTag,
  DisputePriorityBadge,
  DisputeStatusTag,
  DisputeSuggestionChip,
} from "./DisputeTags";

export function ManagerDisputesList({ disputes }: ManagerDisputesListProps) {
  return (
    <ul className="divide-y divide-line">
      {disputes.map((dispute) => {
        const isOpen = dispute.status === DisputeStatusEnum.Open;
        const firstReason = dispute.ai_reasons[0] ?? "";
        return (
          <li key={dispute.id}>
            <Link href={`/disputes/${dispute.id}`} className="flex items-start gap-3 px-4 py-3.5 hover:bg-fg/3 transition">
              <div className="min-w-0 flex-1 space-y-1.5">
                <div className="flex flex-wrap items-center gap-1.5">
                  <DisputePriorityBadge label={dispute.priority_label} score={dispute.priority} />
                  <DisputeSuggestionChip suggestion={dispute.suggestion} />
                  <DisputeAiSourceTag source={dispute.ai_source} />
                  {!isOpen && <DisputeStatusTag status={dispute.status} />}
                </div>
                <div className="text-sm text-fg">
                  <span className="font-medium">Order {shortOrderId(dispute.order_id)}</span>
                  <span className="text-fg-muted">
                    {" · "}
                    {REASON_LABELS[dispute.reason] ?? dispute.reason}
                    {dispute.order && ` · ${formatCurrency(dispute.order.total, dispute.order.currency)}`}
                  </span>
                </div>
                <div className="text-xs text-fg-dim">
                  {dispute.order?.merchant}
                  {dispute.user_email && ` · ${dispute.user_email}`}
                  {` · ${formatRelativeTime(isOpen ? dispute.created_at : dispute.decided_at ?? dispute.created_at)}`}
                </div>
                {firstReason && <p className="text-xs text-fg-2 line-clamp-2">{firstReason}</p>}
              </div>
              <ChevronRight className="w-4 h-4 mt-1 shrink-0 text-fg-dim" strokeWidth={1.8} />
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
