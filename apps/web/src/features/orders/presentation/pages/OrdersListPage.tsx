"use client";

import React, { useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Info, Receipt, Search, SearchX } from "lucide-react";
import { Skeleton, SkeletonRow } from "@/components/Skeleton";
import { OrderFilterTabEnum } from "../../enums";
import { useOrderCounts } from "../../hooks/useOrderCounts";
import { useOrdersManagement } from "../../hooks/useOrdersManagement";
import { OrderSummary } from "../../types";
import { OrderCardsMobile } from "../components/OrderCardsMobile";
import { OrdersTableDesktop } from "../components/OrdersTableDesktop";

const EMPTY_TEXT: Record<OrderFilterTabEnum, string> = {
  [OrderFilterTabEnum.All]: "When your agent checks out, each order shows up here with every check Sepilo ran.",
  [OrderFilterTabEnum.NeedsApproval]: "Nothing is waiting for you. Held orders appear here until you approve or decline.",
  [OrderFilterTabEnum.Paid]: "No orders have been paid yet.",
  [OrderFilterTabEnum.Blocked]: "Nothing has been blocked. Orders that fail a check are stopped before payment.",
  [OrderFilterTabEnum.InProgress]: "No orders are being checked right now.",
};

const TABS = Object.values(OrderFilterTabEnum) as string[];

const TAB_LABELS: Array<{ id: OrderFilterTabEnum; label: string }> = [
  { id: OrderFilterTabEnum.All, label: "All" },
  { id: OrderFilterTabEnum.NeedsApproval, label: "Needs approval" },
  { id: OrderFilterTabEnum.Paid, label: "Paid" },
  { id: OrderFilterTabEnum.Blocked, label: "Blocked" },
  { id: OrderFilterTabEnum.InProgress, label: "Checking" },
];

function matchesQuery(order: OrderSummary, query: string): boolean {
  const needle = query.trim().toLowerCase();
  if (needle.length === 0) return true;
  const titles = (order.cart ?? []).map((item) => item.title.toLowerCase());
  return order.merchant.toLowerCase().includes(needle) || titles.some((title) => title.includes(needle));
}

function ListSkeleton() {
  return (
    <div className="space-y-2 p-3" role="status" aria-label="Loading orders">
      <Skeleton style={{ height: "1rem", width: "30%" }} />
      <SkeletonRow />
      <SkeletonRow />
      <SkeletonRow />
      <SkeletonRow />
    </div>
  );
}

export function OrdersListPage() {
  const router = useRouter();
  const params = useSearchParams();
  const requested = params.get("view") ?? "";
  const currentTab = (TABS.includes(requested) ? requested : OrderFilterTabEnum.All) as OrderFilterTabEnum;
  const setCurrentTab = (tab: OrderFilterTabEnum) =>
    router.replace(tab === OrderFilterTabEnum.All ? "/orders" : `/orders?view=${tab}`, { scroll: false });

  const [query, setQuery] = useState("");
  const { orders, isLoadingOrders } = useOrdersManagement(currentTab);
  const { counts } = useOrderCounts();

  const visibleOrders = orders.filter((order) => matchesQuery(order, query));
  const hasNoOrders = orders.length === 0;
  const hasNoMatches = !hasNoOrders && visibleOrders.length === 0;

  return (
    <div>
      <div className="mb-6 flex flex-col sm:flex-row sm:items-end justify-between gap-3">
        <div className="space-y-1">
          <h1 className="text-xl font-semibold tracking-tight">Orders</h1>
          <p className="text-sm text-fg-muted max-w-2xl">
            Every checkout your agents attempted. Sepilo holds the payment, runs its checks, then pays, blocks, or asks you.
          </p>
        </div>
        <Link
          href="/orders/checks"
          className="inline-flex items-center gap-1.5 self-start sm:self-auto shrink-0 text-xs font-medium text-blue-400 hover:text-blue-300 transition"
        >
          <Info className="w-3.5 h-3.5" strokeWidth={2} aria-hidden="true" />
          What are the 32 security checks?
        </Link>
      </div>

      <div role="tablist" aria-label="Order status" className="flex items-center gap-1 mb-4 border-b border-line overflow-x-auto whitespace-nowrap -mx-4 px-4 sm:mx-0 sm:px-0">
        {TAB_LABELS.map((tab) => {
          const isSelected = tab.id === currentTab;
          const count = counts ? counts[tab.id] : null;
          const isUrgent = tab.id === OrderFilterTabEnum.NeedsApproval && count !== null && count > 0;
          return (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={isSelected}
              onClick={() => setCurrentTab(tab.id)}
              className={`relative inline-flex items-center gap-1.5 px-3 h-10 text-[13px] font-medium transition ${
                isSelected ? "text-fg" : "text-fg-muted hover:text-fg"
              }`}
            >
              {tab.label}
              {count !== null && (
                <span
                  className={`min-w-5 rounded-full px-1.5 text-center text-[11px] leading-5 tabular-nums ${
                    isUrgent
                      ? "bg-amber-500/15 text-amber-400 border border-amber-500/30"
                      : "bg-fg/6 text-fg-dim"
                  }`}
                >
                  {count}
                </span>
              )}
              {isSelected && <span className="absolute left-2 right-2 -bottom-px h-0.5 rounded-full bg-blue-500" />}
            </button>
          );
        })}
      </div>

      <div className="relative mb-4 max-w-md">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-fg-dim" strokeWidth={1.8} aria-hidden="true" />
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search by item or store"
          aria-label="Search orders by item or store"
          className="saas-input h-10 w-full pl-9!"
        />
      </div>

      <div className="saas-card overflow-hidden">
        {isLoadingOrders ? (
          <ListSkeleton />
        ) : hasNoOrders ? (
          <div className="flex flex-col items-center text-center px-6 py-14">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-fg/5 text-fg-muted mb-4">
              <Receipt className="w-5 h-5" strokeWidth={1.8} />
            </span>
            <h3 className="text-sm font-semibold text-fg">No orders here</h3>
            <p className="mt-1 text-sm text-fg-muted max-w-sm">{EMPTY_TEXT[currentTab]}</p>
          </div>
        ) : hasNoMatches ? (
          <div className="flex flex-col items-center text-center px-6 py-14">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-fg/5 text-fg-muted mb-4">
              <SearchX className="w-5 h-5" strokeWidth={1.8} />
            </span>
            <h3 className="text-sm font-semibold text-fg">No matching orders</h3>
            <p className="mt-1 text-sm text-fg-muted max-w-sm">Nothing here matches &ldquo;{query.trim()}&rdquo;. Try an item name or a store.</p>
          </div>
        ) : (
          <>
            <OrderCardsMobile orders={visibleOrders} />
            <OrdersTableDesktop orders={visibleOrders} />
          </>
        )}
      </div>
    </div>
  );
}
