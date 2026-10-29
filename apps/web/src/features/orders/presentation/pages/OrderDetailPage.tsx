"use client";

import React from "react";
import Link from "next/link";
import { ArrowLeft, ArrowRight, FileCheck2, Shield, Wallet } from "lucide-react";
import { RaiseDisputeSection } from "@/features/disputes/presentation/components/RaiseDisputeSection";
import { OrderStatusEnum } from "../../enums";
import { useOrdersManagement } from "../../hooks/useOrdersManagement";
import { OrderDetailPageProps } from "../../pageTypes";
import { formatCurrency, formatRelativeTime, orderStatusTag } from "../../utils";
import { OrderApprovalActions } from "../components/OrderApprovalActions";
import { OrderCartItemsTable } from "../components/OrderCartItemsTable";
import { SecurityChecksTimeline } from "../components/SecurityChecksTimeline";

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
    return (
      <div className="p-8 text-center text-sm text-fg-muted">
        Loading order details...
      </div>
    );
  }

  const { order, checks } = orderDetail;

  const isAwaitingPayment = order.status === OrderStatusEnum.AwaitingPayment && Boolean(order.pay_url);
  const { label: statusLabel, style: statusStyle } = orderStatusTag(order.status);

  const isApprovalRequired = order.status === OrderStatusEnum.PendingApproval;
  const isProcessingApproval = isApprovingOrder || isDecliningOrder;

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <Link
          href="/orders"
          className="inline-flex items-center gap-1.5 text-xs text-fg-muted hover:text-fg transition"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          Back to orders
        </Link>
      </div>

      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-line">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-xl font-semibold tracking-tight">
              Order {order.id.slice(-6).toUpperCase()}
            </h1>
            <span className={`px-2.5 py-0.5 rounded-full text-xs font-medium ${statusStyle}`}>
              {statusLabel}
            </span>
          </div>
          <div className="mt-1 text-xs text-fg-dim">
            Placed at {order.merchant} · {formatRelativeTime(order.created_at)}
          </div>
        </div>

        <div className="text-right">
          <div className="text-2xl font-bold tracking-tight text-fg">
            {formatCurrency(order.total, order.currency)}
          </div>
          <div className="text-xs text-fg-muted">Total amount</div>
        </div>
      </div>

      {isAwaitingPayment && order.pay_url && (
        <div className="saas-card px-5 py-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div>
            <div className="text-sm font-semibold text-fg">Approve the payment in PayPal</div>
            <p className="mt-0.5 text-xs text-fg-muted">
              PayPal holds the money while Sepilo checks the order, then charges or releases it. After this first
              approval your agent pays on its own.
            </p>
          </div>
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

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          <div className="saas-card overflow-hidden">
            <div className="px-5 py-4 border-b border-line">
              <h2 className="text-sm font-semibold text-fg">Cart Items</h2>
            </div>
            <OrderCartItemsTable
              items={order.cart || []}
              currency={order.currency}
            />
          </div>
        </div>

        <div className="space-y-6">
          <div className="saas-card overflow-hidden">
            <div className="px-5 py-4 border-b border-line flex items-center justify-between">
              <h2 className="text-sm font-semibold text-fg flex items-center gap-2">
                <Shield className="w-4 h-4 text-blue-400" />
                Security Pipeline
              </h2>
            </div>
            <SecurityChecksTimeline checks={checks} />
          </div>

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
