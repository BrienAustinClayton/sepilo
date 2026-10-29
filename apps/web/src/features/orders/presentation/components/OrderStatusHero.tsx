"use client";

import React from "react";
import { OrderStatusHeroProps } from "../../componentTypes";
import { TONE, ToneKey, buildStatusHero, formatAbsoluteTime, formatCurrency, formatRelativeTime } from "../../utils";
import { OrderStatusIcon } from "./OrderStatusPill";

const CARD_TONE: Record<ToneKey, string> = {
  success: "border-emerald-500/30",
  danger: "border-rose-500/30",
  warning: "border-amber-500/30",
  brand: "border-blue-500/30",
};

const TITLE_TONE: Record<ToneKey, string> = {
  success: "text-emerald-400",
  danger: "text-rose-400",
  warning: "text-amber-400",
  brand: "text-blue-400",
};

export function OrderStatusHero({ order, preflight, children }: OrderStatusHeroProps) {
  const hero = buildStatusHero(order, preflight);

  return (
    <section aria-labelledby="order-status" className={`saas-card p-5 sm:p-6 ${CARD_TONE[hero.tone]}`}>
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-4">
        <div className="flex min-w-0 flex-1 basis-72 items-start gap-4">
          <span className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl ${TONE[hero.tone]}`}>
            <OrderStatusIcon status={order.status} className="h-6 w-6" />
          </span>
          <div className="min-w-0">
            <div className="text-xs font-medium text-fg-dim">Order {order.id.slice(-6).toUpperCase()}</div>
            <h1 id="order-status" className={`mt-0.5 text-2xl font-semibold tracking-tight ${TITLE_TONE[hero.tone]}`}>
              {hero.title}
            </h1>
            <p className="mt-1.5 text-sm text-fg-2">{hero.sentence}</p>
          </div>
        </div>

        <div className="sm:text-right">
          <div className="text-3xl font-bold tracking-tight tabular-nums text-fg">
            {formatCurrency(order.total, order.currency)}
          </div>
          <div className="mt-0.5 text-xs text-fg-muted">
            {order.merchant} {"·"}{" "}
            <time dateTime={order.created_at} title={formatAbsoluteTime(order.created_at)}>
              {formatRelativeTime(order.created_at)}
            </time>
          </div>
        </div>
      </div>
      {children}
    </section>
  );
}
