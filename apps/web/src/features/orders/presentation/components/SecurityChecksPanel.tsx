"use client";

import React, { useId, useState } from "react";
import Link from "next/link";
import { Check, ChevronDown, Info, LucideIcon, MailX, ThumbsUp, X } from "lucide-react";
import { CHECK_INFO } from "../../constants";
import { SecurityChecksPanelProps } from "../../componentTypes";
import { OrderStatusEnum, PreflightStatusEnum } from "../../enums";
import { PreflightItem } from "../../types";
import { PreflightGroupView, countPreflight, describePreflight, groupPreflight, isInProgress } from "../../utils";

interface StatusLook {
  Icon: LucideIcon;
  text: string;
  bar: string;
  label: string;
}

const STATUS_LOOK: Record<PreflightStatusEnum, StatusLook> = {
  [PreflightStatusEnum.Pass]: { Icon: Check, text: "text-emerald-400", bar: "bg-emerald-500", label: "Passed" },
  [PreflightStatusEnum.Fail]: { Icon: X, text: "text-rose-400", bar: "bg-rose-500", label: "Failed" },
  [PreflightStatusEnum.Accepted]: { Icon: ThumbsUp, text: "text-amber-400", bar: "bg-amber-500", label: "Accepted by you" },
  [PreflightStatusEnum.NotSent]: { Icon: MailX, text: "text-fg-dim", bar: "bg-fg/20", label: "Email not sent" },
};

type FilterKey = "all" | "failed" | "accepted";

function StatusIcon({ status }: { status: PreflightStatusEnum }) {
  const { Icon, text, label } = STATUS_LOOK[status];
  return (
    <span className={`shrink-0 ${text}`} role="img" aria-label={label}>
      <Icon className="h-4 w-4" strokeWidth={2.2} aria-hidden="true" />
    </span>
  );
}

function CheckRow({ item }: { item: PreflightItem }) {
  const [isOpen, setIsOpen] = useState(false);
  const panelId = useId();
  const info = CHECK_INFO[item.id];
  const isPassing = item.status === PreflightStatusEnum.Pass;
  const note =
    item.status === PreflightStatusEnum.Accepted
      ? `Accepted by you. ${item.detail}`.trim()
      : item.status === PreflightStatusEnum.NotSent
        ? "Not sent because another check did not pass."
        : item.detail;

  return (
    <li>
      <button
        type="button"
        onClick={() => setIsOpen((open) => !open)}
        aria-expanded={isOpen}
        aria-controls={panelId}
        className="flex w-full items-start gap-3 px-4 py-3 text-left transition hover:bg-fg/3"
      >
        <span className="mt-0.5">
          <StatusIcon status={item.status} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-baseline gap-x-2">
            <span className="text-sm font-medium text-fg">{item.label}</span>
            <span className="font-mono text-[11px] text-fg-dim">{item.id}</span>
          </span>
          {!isPassing && note && (
            <span className={`mt-0.5 block text-xs ${STATUS_LOOK[item.status].text}`}>{note}</span>
          )}
          {info && <span className="mt-0.5 block text-xs text-fg-muted">{info.what}</span>}
        </span>
        <ChevronDown
          className={`mt-0.5 h-4 w-4 shrink-0 text-fg-dim transition-transform ${isOpen ? "rotate-180" : ""}`}
          strokeWidth={2}
          aria-hidden="true"
        />
      </button>
      {isOpen && info && (
        <div id={panelId} className="space-y-1.5 bg-fg/2 px-4 py-3 pl-11 text-xs text-fg-muted">
          <p>
            <span className="font-medium text-fg-2">Why it matters: </span>
            {info.why}
          </p>
          <p>
            <span className="font-medium text-fg-2">If it fails: </span>
            {info.onFail}
          </p>
        </div>
      )}
    </li>
  );
}

function CheckGroupSection({ view, isOpen, onToggle }: { view: PreflightGroupView; isOpen: boolean; onToggle: () => void }) {
  const listId = useId();
  const { group, items, passed, expected, worst } = view;
  const isClean = worst === PreflightStatusEnum.Pass;

  return (
    <section className="border-t border-line first:border-t-0">
      <h3>
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={isOpen}
          aria-controls={listId}
          className="flex min-h-12 w-full items-center gap-3 px-4 py-2.5 text-left transition hover:bg-fg/3"
        >
          <StatusIcon status={worst} />
          <span className="min-w-0 flex-1">
            <span className="block text-sm font-semibold text-fg">{group.title}</span>
            <span className="block truncate text-xs text-fg-dim">{group.blurb}</span>
          </span>
          <span className="flex shrink-0 items-center gap-2 text-xs tabular-nums">
            {!isClean && <span className={`font-medium ${STATUS_LOOK[worst].text}`}>{STATUS_LOOK[worst].label}</span>}
            <span className="text-fg-dim">
              {passed}/{expected}
            </span>
          </span>
          <ChevronDown
            className={`h-4 w-4 shrink-0 text-fg-dim transition-transform ${isOpen ? "rotate-180" : ""}`}
            strokeWidth={2}
            aria-hidden="true"
          />
        </button>
      </h3>
      {isOpen && (
        <ul id={listId} className="divide-y divide-line border-t border-line">
          {items.map((item) => (
            <CheckRow key={item.id} item={item} />
          ))}
        </ul>
      )}
    </section>
  );
}

const CHIP_BASE = "inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-xs font-medium transition";

export function SecurityChecksPanel({ summary, status }: SecurityChecksPanelProps) {
  const [filter, setFilter] = useState<FilterKey>("all");
  const [overrides, setOverrides] = useState<Record<string, boolean>>({});

  const header = (
    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-5 py-4">
      <h2 className="text-sm font-semibold text-fg">32 security checks</h2>
      <Link href="/orders/checks" className="inline-flex items-center gap-1.5 text-xs font-medium text-blue-400 hover:text-blue-300">
        <Info className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />
        What are these checks?
      </Link>
    </div>
  );

  if (summary === null) {
    return (
      <div id="security-checks" className="saas-card overflow-hidden scroll-mt-20">
        {header}
        <p className="p-6 text-center text-sm text-fg-muted">
          {isInProgress(status) || status === OrderStatusEnum.AwaitingPayment
            ? "The 32 security checks run just before payment. They will appear here when they finish."
            : status === OrderStatusEnum.Captured
              ? "No list of security checks was saved for this order."
              : "32 security checks didn’t run: this order was stopped before payment."}
        </p>
      </div>
    );
  }

  const counts = countPreflight(summary.items);
  const sorted = [...summary.items].sort((a, b) => a.id.localeCompare(b.id));
  const matches = (item: PreflightItem) =>
    filter === "all" ||
    (filter === "failed" && item.status === PreflightStatusEnum.Fail) ||
    (filter === "accepted" && item.status === PreflightStatusEnum.Accepted);
  const views = groupPreflight(summary.items)
    .map((view) => ({ ...view, items: view.items.filter(matches) }))
    .filter((view) => view.items.length > 0);

  const isOpen = (view: PreflightGroupView) =>
    overrides[view.group.key] ??
    (filter !== "all" || view.worst === PreflightStatusEnum.Fail || view.worst === PreflightStatusEnum.Accepted);

  const chips: Array<{ key: FilterKey; label: string; count: number | null }> = [
    { key: "all", label: "All", count: null },
    { key: "failed", label: "Failed", count: counts.failed },
    { key: "accepted", label: "Accepted", count: counts.accepted },
  ];

  return (
    <div id="security-checks" className="saas-card overflow-hidden scroll-mt-20">
      {header}

      <div className="space-y-3 px-5 py-4">
        <p className="text-sm font-medium text-fg">{describePreflight(summary)}</p>

        <div
          className="flex h-2.5 gap-0.5"
          role="img"
          aria-label={`${describePreflight(summary)}. One segment per check.`}
        >
          {sorted.map((item) => (
            <span
              key={item.id}
              title={`${item.id} ${item.label}: ${STATUS_LOOK[item.status].label}`}
              className={`h-full min-w-0 flex-1 rounded-xs ${STATUS_LOOK[item.status].bar}`}
            />
          ))}
        </div>

        <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-fg-muted">
          {Object.values(PreflightStatusEnum).map((value) => {
            const { Icon, text, label } = STATUS_LOOK[value];
            return (
              <li key={value} className="inline-flex items-center gap-1.5">
                <Icon className={`h-3.5 w-3.5 ${text}`} strokeWidth={2.2} aria-hidden="true" />
                {label}
              </li>
            );
          })}
        </ul>

        <div role="group" aria-label="Filter checks" className="flex flex-wrap gap-2">
          {chips.map((chip) => {
            const isActive = filter === chip.key;
            return (
              <button
                key={chip.key}
                type="button"
                aria-pressed={isActive}
                onClick={() => {
                  setFilter(chip.key);
                  setOverrides({});
                }}
                className={`${CHIP_BASE} ${
                  isActive ? "border-blue-500/40 bg-blue-500/10 text-blue-400" : "border-line text-fg-muted hover:text-fg"
                }`}
              >
                {chip.label}
                {chip.count !== null && <span className="tabular-nums">{chip.count}</span>}
              </button>
            );
          })}
        </div>
      </div>

      <div className="border-t border-line">
        {views.length === 0 ? (
          <p className="p-6 text-center text-sm text-fg-muted">
            {filter === "failed" ? "No checks failed." : "You did not need to accept any warnings."}
          </p>
        ) : (
          views.map((view) => (
            <CheckGroupSection
              key={view.group.key}
              view={view}
              isOpen={isOpen(view)}
              onToggle={() => setOverrides((prev) => ({ ...prev, [view.group.key]: !isOpen(view) }))}
            />
          ))
        )}
      </div>
    </div>
  );
}
