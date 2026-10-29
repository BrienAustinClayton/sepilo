"use client";

import React from "react";
import Link from "next/link";
import { ArrowLeft, ArrowRight, FileCheck2, Wallet } from "lucide-react";
import { Skeleton } from "@/components/Skeleton";
import { RaiseDisputeSection } from "@/features/disputes/presentation/components/RaiseDisputeSection";
import { OrderStatusEnum, SecurityCheckStepEnum } from "../../enums";
import { useOrdersManagement } from "../../hooks/useOrdersManagement";
import { OrderDetailPageProps } from "../../pageTypes";
import { readPreflight } from "../../utils";
import { OrderApprovalActions } from "../components/OrderApprovalActions";
import { OrderCartItemsTable } from "../components/OrderCartItemsTable";
import { OrderStatusHero } from "../components/OrderStatusHero";
import { SecurityChecksPanel } from "../components/SecurityChecksPanel";
import { SecurityChecksTimeline } from "../components/SecurityChecksTimeline";
import { ShippingAddressCard } from "../components/ShippingAddressCard";

function DetailSkeleton() {
  return (
    <div className="space-y-6" role="status" aria-label="Loading order">
      <Skeleton style={{ height: "0.875rem", width: "7rem" }} />
      <div className="saas-card space-y-3 p-6">
        <Skeleton style={{ height: "1.75rem", width: "40%" }} />
        <Skeleton style={{ height: "0.875rem", width: "70%" }} />
      </div>
      <div className="saas-card space-y-3 p-6">
        <Skeleton style={{ height: "0.875rem", width: "30%" }} />
        <Skeleton style={{ height: "0.875rem", width: "90%" }} />
        <Skeleton style={{ height: "0.875rem", width: "60%" }} />
      </div>
    </div>
  );
}

export function OrderDetailPage({ orderId }: OrderDetailPageProps) {
  const {
    orderDetail,
    isLoadingOrderDetail,
    approveOrder,
    isApprovingOrder,
    declineOrder,
    isDecliningOrder,
  } = useOrdersManagement(undefined, orderId);

  const isDataMissing = !isLoadingOrderDetail && orderDetail === null;
  if (isDataMissing) {
    return (
      <div className="p-8 text-center text-sm text-fg-muted">
        Order not found.
      </div>
    );
  }

  if (isLoadingOrderDetail || !orderDetail) {
    return <DetailSkeleton />;
  }

  const { order, checks } = orderDetail;

  const preflightRow = [...checks].reverse().find((check) => check.step === SecurityCheckStepEnum.Preflight);
  const preflight = preflightRow ? readPreflight(preflightRow.details) : null;

  const isAwaitingPayment = order.status === OrderStatusEnum.AwaitingPayment && Boolean(order.pay_url);
  const isApprovalRequired = order.status === OrderStatusEnum.PendingApproval;
  const isProcessingApproval = isApprovingOrder || isDecliningOrder;

  return (
    <div className={`space-y-6 ${isApprovalRequired ? "pb-24 sm:pb-0" : ""}`}>
      <Link
        href="/orders"
        className="inline-flex items-center gap-1.5 text-xs text-fg-muted hover:text-fg transition"
      >
        <ArrowLeft className="w-3.5 h-3.5" />
        Back to orders
      </Link>

      <OrderStatusHero order={order} preflight={preflight}>
        {isAwaitingPayment && order.pay_url && (
          <div className="mt-5 flex flex-col gap-3 border-t border-line pt-4 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-xs text-fg-muted max-w-xl">
              PayPal holds the money while Sepilo checks the order, then charges or releases it. After this first
              approval your agent pays on its own.
            </p>
            <a href={order.pay_url} className="intentlock-btn-primary inline-flex items-center justify-center gap-2 whitespace-nowrap shrink-0">
              <Wallet className="w-4 h-4" strokeWidth={1.8} />
              Pay with PayPal
            </a>
          </div>
        )}
        {isApprovalRequired && (
          <OrderApprovalActions
            orderId={order.id}
            timeoutAt={order.approval_timeout_at}
            total={order.total}
            onApprove={(confirmTotal?: string) => approveOrder({ orderId: order.id, confirmTotal })}
            onDecline={() => declineOrder(order.id)}
            isProcessing={isProcessingApproval}
          />
        )}
      </OrderStatusHero>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6 min-w-0">
          <div className="saas-card overflow-hidden">
            <div className="px-5 py-4 border-b border-line">
              <h2 className="text-sm font-semibold text-fg">Cart items</h2>
            </div>
            <OrderCartItemsTable
              items={order.cart || []}
              currency={order.currency}
            />
          </div>

          <SecurityChecksPanel summary={preflight} status={order.status} />
        </div>

        <div className="space-y-6 min-w-0">
          <div className="saas-card overflow-hidden">
            <div className="px-5 py-4 border-b border-line">
              <h2 className="text-sm font-semibold text-fg">How Sepilo checked this order</h2>
            </div>
            <SecurityChecksTimeline checks={checks} />
          </div>

          {order.shipping_address && <ShippingAddressCard address={order.shipping_address} />}

          <RaiseDisputeSection orderId={order.id} isPaid={order.status === OrderStatusEnum.Captured} />

          <Link href={`/proof/${order.id}`} className="saas-card flex items-center gap-3 px-5 py-4 hover:border-blue-500/40 transition">
            <FileCheck2 className="w-4 h-4 text-blue-400 shrink-0" strokeWidth={1.8} />
            <span className="min-w-0 flex-1">
              <span className="block text-sm font-semibold text-fg">View Proof of Intent</span>
              <span className="block text-xs text-fg-muted">Signed record of the request, the rules and every check.</span>
            </span>
            <ArrowRight className="w-4 h-4 text-fg-dim shrink-0" />
          </Link>
        </div>
      </div>
    </div>
  );
}
