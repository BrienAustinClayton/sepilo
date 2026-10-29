import React from "react";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { formatCurrency } from "@/features/orders/utils";
import {
  DisputeChecksPanelProps,
  DisputeSummaryProps,
  DisputeTriagePanelProps,
} from "../../componentTypes";
import { REASON_LABELS } from "../../constants";
import { DisputeStatusEnum } from "../../enums";
import { formatDateTime, shortOrderId } from "../../utils";
import { DisputeAiSourceTag, DisputeStatusTag, DisputeSuggestionChip } from "./DisputeTags";

export function DisputeSummaryCard({ dispute }: DisputeSummaryProps) {
  const isDecided = dispute.status !== DisputeStatusEnum.Open;
  return (
    <div className="saas-card overflow-hidden">
      <div className="px-5 py-4 border-b border-line flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-fg">What the customer says</h2>
        <DisputeStatusTag status={dispute.status} />
      </div>
      <dl className="p-5 space-y-3 text-sm">
        <div>
          <dt className="text-xs text-fg-dim">Reason</dt>
          <dd className="text-fg">{REASON_LABELS[dispute.reason] ?? dispute.reason}</dd>
        </div>
        <div>
          <dt className="text-xs text-fg-dim">Description</dt>
          <dd className="text-fg-2 whitespace-pre-wrap wrap-anywhere">{dispute.description}</dd>
        </div>
        <div>
          <dt className="text-xs text-fg-dim">Opened</dt>
          <dd className="text-fg-2">{formatDateTime(dispute.created_at)}</dd>
        </div>
        {isDecided && (
          <div>
            <dt className="text-xs text-fg-dim">Decision{dispute.decided_at ? ` · ${formatDateTime(dispute.decided_at)}` : ""}</dt>
            <dd className="text-fg-2 whitespace-pre-wrap wrap-anywhere">{dispute.decision_note ?? "No note"}</dd>
          </div>
        )}
        {dispute.order && (
          <div>
            <dt className="text-xs text-fg-dim">Order</dt>
            <dd>
              <Link
                href={`/orders/${dispute.order_id}`}
                className="inline-flex items-center gap-1.5 text-blue-400 hover:text-blue-300"
              >
                {shortOrderId(dispute.order_id)} · {formatCurrency(dispute.order.total, dispute.order.currency)} at{" "}
                {dispute.order.merchant}
                <ArrowRight className="w-3.5 h-3.5" />
              </Link>
            </dd>
          </div>
        )}
      </dl>
    </div>
  );
}

export function DisputeTriagePanel({ dispute }: DisputeTriagePanelProps) {
  return (
    <div className="saas-card overflow-hidden">
      <div className="px-5 py-4 border-b border-line flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold text-fg mr-auto">Triage</h2>
        <DisputeSuggestionChip suggestion={dispute.suggestion} />
        <DisputeAiSourceTag source={dispute.ai_source} />
      </div>
      {dispute.ai_reasons.length === 0 ? (
        <p className="p-5 text-sm text-fg-muted">No triage notes for this dispute.</p>
      ) : (
        <ul className="p-5 space-y-2 list-disc list-inside text-sm text-fg-2 marker:text-fg-dim">
          {dispute.ai_reasons.map((reason, index) => (
            <li key={index} className="wrap-anywhere">
              {reason}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function DisputeChecksPanel({ detail }: DisputeChecksPanelProps) {
  const { checks, user_history: history } = detail;
  return (
    <>
      <div className="saas-card overflow-hidden">
        <div className="px-5 py-4 border-b border-line">
          <h2 className="text-sm font-semibold text-fg">Order checks</h2>
        </div>
        {checks.length === 0 ? (
          <p className="p-5 text-sm text-fg-muted">No checks recorded.</p>
        ) : (
          <ul className="divide-y divide-line">
            {checks.map((check, index) => (
              <li key={index} className="flex items-center justify-between gap-3 px-5 py-2.5 text-sm">
                <span className="text-fg-2">{check.step.replace(/_/g, " ")}</span>
                <span className="text-xs text-fg-muted tabular-nums">
                  {check.result}
                  {check.score !== null && ` · ${check.score}`}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="saas-card overflow-hidden">
        <div className="px-5 py-4 border-b border-line">
          <h2 className="text-sm font-semibold text-fg">Customer history</h2>
        </div>
        <dl className="grid grid-cols-3 divide-x divide-line text-center">
          <div className="p-4">
            <dd className="text-lg font-semibold tabular-nums text-fg">{history.total}</dd>
            <dt className="text-xs text-fg-dim">Other disputes</dt>
          </div>
          <div className="p-4">
            <dd className="text-lg font-semibold tabular-nums text-fg">{history.refunded_90d}</dd>
            <dt className="text-xs text-fg-dim">Refunded, 90 days</dt>
          </div>
          <div className="p-4">
            <dd className="text-lg font-semibold tabular-nums text-fg">{history.open}</dd>
            <dt className="text-xs text-fg-dim">Open now</dt>
          </div>
        </dl>
      </div>
    </>
  );
}
