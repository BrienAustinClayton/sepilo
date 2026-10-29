"use client";

import React, { useState } from "react";
import Link from "next/link";
import { ArrowLeft, RefreshCw } from "lucide-react";
import { OrderCartItemsTable } from "@/features/orders/presentation/components/OrderCartItemsTable";
import { formatCurrency } from "@/features/orders/utils";
import { Button } from "@/shared/presentation/components/Button";
import { ButtonVariantEnum } from "@/shared/enums";
import { DisputeDetailPageProps } from "../../pageTypes";
import { DisputeStatusEnum } from "../../enums";
import { useDisputeDetail } from "../../hooks/useDisputeDetail";
import { useDisputeRole } from "../../hooks/useDisputeRole";
import { useMyDispute } from "../../hooks/useMyDisputes";
import { shortOrderId, toCartItems } from "../../utils";
import { DisputeDecisionForm } from "../components/DisputeDecisionForm";
import { DisputeChecksPanel, DisputeSummaryCard, DisputeTriagePanel } from "../components/DisputePanels";
import { DisputePriorityBadge } from "../components/DisputeTags";

const NOT_FOUND = <div className="p-8 text-center text-sm text-fg-muted">Dispute not found.</div>;
const LOADING = <div className="p-8 text-center text-sm text-fg-muted">Loading dispute...</div>;

function BackLink() {
  return (
    <Link href="/disputes" className="inline-flex items-center gap-1.5 text-xs text-fg-muted hover:text-fg transition">
      <ArrowLeft className="w-3.5 h-3.5" />
      Back to disputes
    </Link>
  );
}

function CustomerDisputeView({ disputeId }: DisputeDetailPageProps) {
  const { dispute, isLoadingDispute, isMissing } = useMyDispute(disputeId, true);

  if (isLoadingDispute) return LOADING;
  if (isMissing || dispute === null) return NOT_FOUND;

  return (
    <div className="space-y-6 max-w-2xl">
      <BackLink />
      <h1 className="text-xl font-semibold tracking-tight">Dispute for order {shortOrderId(dispute.order_id)}</h1>
      <DisputeSummaryCard dispute={dispute} />
    </div>
  );
}

function ManagerDisputeView({ disputeId }: DisputeDetailPageProps) {
  const { detail, isLoadingDetail, isMissing, retriage, isRetriaging, decide, isDeciding } = useDisputeDetail(
    disputeId,
    true,
  );
  const [retriageError, setRetriageError] = useState<string | null>(null);

  if (isLoadingDetail) return LOADING;
  if (isMissing || detail === null) return NOT_FOUND;

  const isOpen = detail.status === DisputeStatusEnum.Open;
  const { order_detail: order } = detail;

  const handleRetriage = () => {
    setRetriageError(null);
    retriage(detail.id).catch((error: Error) => setRetriageError(error.message));
  };

  return (
    <div className="space-y-6">
      <BackLink />

      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-line">
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-xl font-semibold tracking-tight">Dispute for order {shortOrderId(detail.order_id)}</h1>
            <DisputePriorityBadge label={detail.priority_label} score={detail.priority} />
          </div>
          <div className="text-xs text-fg-dim">
            {order.merchant}
            {detail.user_email && ` · ${detail.user_email}`}
          </div>
        </div>
        <div className="flex items-center gap-3 sm:flex-col sm:items-end sm:gap-1">
          <div className="text-2xl font-bold tracking-tight text-fg">{formatCurrency(order.total, order.currency)}</div>
          {isOpen && (
            <Button variant={ButtonVariantEnum.Outline} isLoading={isRetriaging} onClick={handleRetriage}>
              <RefreshCw className="w-4 h-4" strokeWidth={1.8} />
              Re-triage
            </Button>
          )}
        </div>
      </div>

      {retriageError !== null && (
        <p role="alert" className="text-xs text-rose-400">
          {retriageError}
        </p>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          <DisputeSummaryCard dispute={detail} />
          <DisputeTriagePanel dispute={detail} />
          <div className="saas-card overflow-hidden">
            <div className="px-5 py-4 border-b border-line">
              <h2 className="text-sm font-semibold text-fg">Cart items</h2>
            </div>
            <OrderCartItemsTable items={toCartItems(order.cart)} currency={order.currency} />
          </div>
        </div>

        <div className="space-y-6">
          {isOpen && (
            <div className="saas-card overflow-hidden">
              <div className="px-5 py-4 border-b border-line">
                <h2 className="text-sm font-semibold text-fg">Your decision</h2>
              </div>
              <DisputeDecisionForm
                total={order.total}
                isProcessing={isDeciding}
                onSubmit={async (payload) => {
                  await decide({ disputeId: detail.id, payload });
                }}
              />
            </div>
          )}
          <DisputeChecksPanel detail={detail} />
        </div>
      </div>
    </div>
  );
}

export function DisputeDetailPage({ disputeId }: DisputeDetailPageProps) {
  const { isLoadingRole, isManager } = useDisputeRole();

  if (isLoadingRole) return LOADING;
  return isManager ? <ManagerDisputeView disputeId={disputeId} /> : <CustomerDisputeView disputeId={disputeId} />;
}
