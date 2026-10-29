"use client";

import React from "react";
import Link from "next/link";
import { ArrowRight, Circle, CircleCheck, MapPin, MessageSquarePlus, Receipt, TriangleAlert } from "lucide-react";
import { OrderCardsMobile } from "@/features/orders/presentation/components/OrderCardsMobile";
import { OrdersTableDesktop } from "@/features/orders/presentation/components/OrdersTableDesktop";
import { useMe } from "@/lib/useMe";
import { useDashboardSummary } from "../../hooks/useDashboardSummary";
import { SetupStep, StatCardProps } from "../../types";

function StatCard({ label, value, hint }: StatCardProps) {
  return (
    <div className="saas-card p-5">
      <div className="text-xs font-medium text-fg-dim">{label}</div>
      <div className="mt-2 text-2xl font-semibold tracking-tight tabular-nums text-fg">{value}</div>
      <div className="mt-1 text-xs text-fg-dim">{hint}</div>
    </div>
  );
}

export function DashboardPage() {
  const { summary } = useDashboardSummary();
  const me = useMe();
  const needsAddress = me !== null && me.has_address === false;

  const steps: SetupStep[] = summary
    ? [
        {
          done: summary.payment_connected,
          label: "Connect a payment method",
          body: "Sepilo holds funds and only pays once checks pass.",
          href: "/payment",
        },
        {
          done: summary.agents_active > 0,
          label: "Create your shopping agent",
          body: "Sepilo runs it for you, or connect an agent you already use.",
          href: "/agents",
        },
        {
          done: summary.rules_active > 0,
          label: "Set a spending rule",
          body: "Budget, categories and stores your agent is allowed to use.",
          href: "/rules",
        },
        {
          done: summary.requests > 0,
          label: "Ask Sepilo to buy something",
          body: "Chat with your agent; it suggests products within your rules.",
          href: "/chat",
        },
      ]
    : [];

  const setupLeft = steps.filter((step: SetupStep) => !step.done).length;
  const hasNeedsApproval = summary !== null && summary.needs_approval > 0;
  const recentOrders = summary && Array.isArray(summary.recent_orders) ? summary.recent_orders : [];

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4">
        <div className="space-y-1">
          <h1 className="text-xl font-semibold tracking-tight">Welcome back</h1>
          <p className="text-sm text-fg-muted">What your agents bought this month, and what Sepilo stopped.</p>
        </div>
        <Link href="/chat" className="intentlock-btn-primary">
          <MessageSquarePlus className="w-4 h-4" strokeWidth={1.8} />
          Start shopping
        </Link>
      </div>

      {needsAddress && (
        <div className="saas-card flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-4 border-blue-500/30 bg-blue-500/5">
          <div className="flex items-center gap-3">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-500/10 text-blue-400">
              <MapPin className="w-4 h-4" strokeWidth={1.8} />
            </span>
            <div>
              <div className="text-sm font-medium text-fg">Add your shipping address.</div>
              <div className="text-xs text-fg-muted">Sepilo won&apos;t pay for any order without one.</div>
            </div>
          </div>
          <Link href="/address" className="intentlock-btn-primary btn-sm">
            Add address
            <ArrowRight className="w-3.5 h-3.5" strokeWidth={1.8} />
          </Link>
        </div>
      )}

      {hasNeedsApproval && summary && (
        <div className="saas-card flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-4 border-amber-500/30 bg-amber-500/5">
          <div className="flex items-center gap-3">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-amber-500/10 text-amber-400">
              <TriangleAlert className="w-4 h-4" strokeWidth={1.8} />
            </span>
            <div>
              <div className="text-sm font-medium text-fg">
                {summary.needs_approval === 1
                  ? "1 order is waiting for you"
                  : `${summary.needs_approval} orders are waiting for you`}
              </div>
              <div className="text-xs text-fg-muted">Funds are on hold. Nothing is charged until you approve.</div>
            </div>
          </div>
          <Link href="/orders?view=needs_approval" className="intentlock-btn-outline btn-sm">
            Review
            <ArrowRight className="w-3.5 h-3.5" strokeWidth={1.8} />
          </Link>
        </div>
      )}

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label="Orders"
          value={summary ? String(summary.month.orders) : "–"}
          hint="Checked this month"
        />
        <StatCard
          label="Paid"
          value={summary ? String(summary.month.paid) : "–"}
          hint="Passed every check"
        />
        <StatCard
          label="Blocked"
          value={summary ? String(summary.month.blocked) : "–"}
          hint="Stopped before payment"
        />
        <StatCard
          label="Spent"
          value={summary ? `$${Number(summary.month.spent).toFixed(2)}` : "–"}
          hint="Captured this month"
        />
      </div>

      {summary && (
        <div className="saas-card overflow-hidden">
          <div className="flex items-center justify-between px-5 py-4 border-b border-line">
            <h2 className="text-sm font-semibold text-fg">Recent orders</h2>
            <Link href="/orders" className="text-xs font-medium text-blue-400 hover:text-blue-300">
              View all
            </Link>
          </div>
          {recentOrders.length === 0 ? (
            <div className="flex flex-col items-center text-center px-6 py-12">
              <Receipt className="w-5 h-5 text-fg-muted mb-3" strokeWidth={1.8} />
              <div className="text-sm font-semibold text-fg">No orders yet</div>
              <p className="mt-1 text-sm text-fg-muted max-w-sm">
                When your agent checks out, the order and every check Sepilo ran on it show up here.
              </p>
            </div>
          ) : (
            <>
              <OrderCardsMobile orders={recentOrders} />
              <OrdersTableDesktop orders={recentOrders} />
            </>
          )}
        </div>
      )}

      {summary && setupLeft > 0 && (
        <div className="saas-card overflow-hidden">
          <div className="px-5 pt-4 pb-3 flex items-center justify-between border-b border-line">
            <div>
              <h2 className="text-sm font-semibold text-fg">Getting started with Sepilo</h2>
              <p className="text-xs text-fg-muted">Set up your account to let agents shop safely.</p>
            </div>
            <span className="text-xs font-medium text-fg-dim">
              {4 - setupLeft} of 4 complete
            </span>
          </div>

          <div className="divide-y divide-line">
            {steps.map((step: SetupStep) => (
              <Link
                key={step.label}
                href={step.href}
                className="flex items-center justify-between p-4 hover:bg-fg/2 transition"
              >
                <div className="flex items-center gap-3">
                  {step.done ? (
                    <CircleCheck className="w-5 h-5 text-emerald-400 shrink-0" />
                  ) : (
                    <Circle className="w-5 h-5 text-fg-dim shrink-0" />
                  )}
                  <div>
                    <div className={`text-sm font-medium ${step.done ? "text-fg line-through opacity-70" : "text-fg"}`}>
                      {step.label}
                    </div>
                    <div className="text-xs text-fg-muted">{step.body}</div>
                  </div>
                </div>

                <ArrowRight className="w-4 h-4 text-fg-dim" />
              </Link>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
