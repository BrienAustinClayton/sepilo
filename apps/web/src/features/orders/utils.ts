import { OrderStatusEnum, PreflightStatusEnum, SecurityCheckStepEnum } from "./enums";
import { CHECK_GROUPS, CheckGroup, checkIdsInGroup } from "./constants";
import { OrderSummary, PreflightItem, PreflightSummary } from "./types";

export function formatCurrency(amount: string | number, currency: string = "USD"): string {
  const numericAmount = Number(amount);
  const isValidNumber = !isNaN(numericAmount);
  if (!isValidNumber) {
    return `${currency} 0.00`;
  }
  return `$${numericAmount.toFixed(2)}`;
}

export function calculateLineTotal(unitPrice: string, qty: number): string {
  const parts = unitPrice.split(".");
  const wholePart = parseInt(parts[0] || "0", 10);
  const fracStr = (parts[1] || "").padEnd(2, "0").slice(0, 2);
  const fracPart = parseInt(fracStr, 10);
  const priceCents = wholePart * 100 + fracPart;
  const totalCents = priceCents * qty;
  const dollars = Math.floor(totalCents / 100);
  const cents = totalCents % 100;
  return `${dollars}.${String(cents).padStart(2, "0")}`;
}

export function formatRelativeTime(isoString: string | null): string {
  if (isoString === null) {
    return "";
  }
  const date = new Date(isoString);
  const diffInSeconds = (Date.now() - date.getTime()) / 1000;
  const isJustNow = diffInSeconds < 60;
  if (isJustNow) {
    return "Just now";
  }
  const isWithinHour = diffInSeconds < 3600;
  if (isWithinHour) {
    return `${Math.floor(diffInSeconds / 60)} min ago`;
  }
  const isWithinDay = diffInSeconds < 86400;
  if (isWithinDay) {
    return `${Math.floor(diffInSeconds / 3600)} h ago`;
  }
  const isWithinWeek = diffInSeconds < 7 * 86400;
  if (isWithinWeek) {
    return `${Math.floor(diffInSeconds / 86400)} d ago`;
  }
  return date.toLocaleDateString();
}

export function formatAbsoluteTime(isoString: string | null): string {
  if (isoString === null) {
    return "";
  }
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function describeItems(order: OrderSummary): string {
  const items = order.cart ?? [];
  const first = items[0];
  if (!first) return "No items";
  return items.length > 1 ? `${first.title} and ${items.length - 1} more` : first.title;
}

export function getStepDisplayName(step: SecurityCheckStepEnum): string {
  const labels: Record<SecurityCheckStepEnum, string> = {
    [SecurityCheckStepEnum.VerifyAgent]: "Verify Agent",
    [SecurityCheckStepEnum.CheckMandate]: "Check Mandate",
    [SecurityCheckStepEnum.AuthorizePayment]: "Authorize Payment",
    [SecurityCheckStepEnum.ScanInjection]: "Scan Injection",
    [SecurityCheckStepEnum.IntentDiff]: "Intent Diff",
    [SecurityCheckStepEnum.GraphRisk]: "Graph Risk",
    [SecurityCheckStepEnum.Preflight]: "32 security checks",
    [SecurityCheckStepEnum.Decide]: "Decide",
    [SecurityCheckStepEnum.CaptureOrVoid]: "Capture or Void",
    [SecurityCheckStepEnum.BuildProof]: "Build Proof",
  };
  return labels[step] || step;
}

export const TONE = {
  success: "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20",
  danger: "bg-rose-500/10 text-rose-400 border border-rose-500/20",
  warning: "bg-amber-500/10 text-amber-400 border border-amber-500/20",
  brand: "bg-blue-500/10 text-blue-400 border border-blue-500/20",
};

const STATUS_TAG: Partial<Record<OrderStatusEnum, { label: string; style: string }>> = {
  [OrderStatusEnum.Captured]: { label: "Paid", style: TONE.success },
  [OrderStatusEnum.Voided]: { label: "Blocked", style: TONE.danger },
  [OrderStatusEnum.Refunded]: { label: "Refunded", style: TONE.brand },
  [OrderStatusEnum.Rejected]: { label: "Blocked", style: TONE.danger },
  [OrderStatusEnum.Failed]: { label: "Failed", style: TONE.danger },
  [OrderStatusEnum.PendingApproval]: { label: "Needs Approval", style: TONE.warning },
  [OrderStatusEnum.AwaitingPayment]: { label: "Pay in PayPal", style: TONE.warning },
};

export function orderStatusTag(status: OrderStatusEnum): { label: string; style: string } {
  return STATUS_TAG[status] ?? { label: "Checking", style: TONE.brand };
}

const PREFLIGHT_TOTAL = 32;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function toPreflightItem(value: unknown): PreflightItem | null {
  if (!isRecord(value)) return null;
  const { id, label, status, detail } = value;
  if (typeof id !== "string" || typeof label !== "string" || typeof status !== "string") return null;
  const detailText = typeof detail === "string" ? detail : "";
  const known = Object.values(PreflightStatusEnum).find((s) => s === status);
  if (!known) return null;
  const isNotSent = known === PreflightStatusEnum.Fail && detailText === "not_sent";
  return {
    id,
    label,
    status: isNotSent ? PreflightStatusEnum.NotSent : known,
    detail: isNotSent ? "" : detailText,
  };
}

export function readPreflight(details: Record<string, unknown> | null): PreflightSummary | null {
  if (!details || !Array.isArray(details.checks)) return null;
  const items = details.checks.map(toPreflightItem).filter((item): item is PreflightItem => item !== null);
  if (items.length === 0) return null;
  const passed = items.filter(
    (item) => item.status === PreflightStatusEnum.Pass || item.status === PreflightStatusEnum.Accepted,
  ).length;
  const total = typeof details.total === "number" ? details.total : PREFLIGHT_TOTAL;
  return { items, passed, total };
}

export interface PreflightCounts {
  passed: number;
  failed: number;
  accepted: number;
  notSent: number;
}

export function countPreflight(items: PreflightItem[]): PreflightCounts {
  const count = (status: PreflightStatusEnum) => items.filter((item) => item.status === status).length;
  const accepted = count(PreflightStatusEnum.Accepted);
  return {
    passed: count(PreflightStatusEnum.Pass) + accepted,
    failed: count(PreflightStatusEnum.Fail),
    accepted,
    notSent: count(PreflightStatusEnum.NotSent),
  };
}

export function describePreflight(summary: PreflightSummary): string {
  const counts = countPreflight(summary.items);
  const parts = [`${counts.passed} of ${summary.total} passed`];
  if (counts.failed > 0) parts.push(`${counts.failed} failed`);
  if (counts.accepted > 0) parts.push(`${counts.accepted} accepted by you`);
  if (counts.notSent > 0) parts.push("email not sent");
  return parts.join(" \u00b7 ");
}

const WORST_ORDER: PreflightStatusEnum[] = [
  PreflightStatusEnum.Fail,
  PreflightStatusEnum.Accepted,
  PreflightStatusEnum.NotSent,
  PreflightStatusEnum.Pass,
];

export function worstStatus(items: PreflightItem[]): PreflightStatusEnum {
  return WORST_ORDER.find((status) => items.some((item) => item.status === status)) ?? PreflightStatusEnum.Pass;
}

export interface PreflightGroupView {
  group: CheckGroup;
  items: PreflightItem[];
  passed: number;
  expected: number;
  worst: PreflightStatusEnum;
}

export function groupPreflight(items: PreflightItem[]): PreflightGroupView[] {
  return CHECK_GROUPS.map((group) => {
    const ids = new Set(checkIdsInGroup(group));
    const inGroup = items.filter((item) => ids.has(item.id)).sort((a, b) => a.id.localeCompare(b.id));
    const counts = countPreflight(inGroup);
    return { group, items: inGroup, passed: counts.passed, expected: ids.size, worst: worstStatus(inGroup) };
  }).filter((view) => view.items.length > 0);
}

export type ToneKey = keyof typeof TONE;

export interface StatusHero {
  title: string;
  tone: ToneKey;
  sentence: string;
}

function summarizeReasons(reasons: string[] | null, fallback: string[]): string {
  const list = (reasons && reasons.length > 0 ? reasons : fallback).filter((r) => r.length > 0);
  if (list.length === 0) return "";
  const shown = list.slice(0, 2).join("; ");
  return list.length > 2 ? `${shown} and ${list.length - 2} more` : shown;
}

export function buildStatusHero(order: OrderSummary, preflight: PreflightSummary | null): StatusHero {
  const failedItems = preflight ? preflight.items.filter((item) => item.status === PreflightStatusEnum.Fail) : [];
  const failedLabels = failedItems.map((item) => item.label);
  const failedText = failedItems.map((item) => (item.detail ? `${item.label} (${item.detail.toLowerCase()})` : item.label));
  const heldBy = failedItems.length === 1 ? "1 security check didn't pass" : `${failedItems.length} security checks didn't pass`;
  const why = summarizeReasons(order.decision_reasons, failedLabels);
  const counts = preflight ? countPreflight(preflight.items) : null;

  switch (order.status) {
    case OrderStatusEnum.Captured: {
      if (preflight && counts && counts.failed === 0 && counts.accepted === 0) {
        return { title: "Paid", tone: "success", sentence: `All ${preflight.total} security checks passed. Paid.` };
      }
      if (preflight && counts && counts.accepted > 0) {
        const warnings = counts.accepted === 1 ? "1 warning" : `${counts.accepted} warnings`;
        return { title: "Paid", tone: "success", sentence: `Paid after you approved it. ${warnings} accepted by you.` };
      }
      return { title: "Paid", tone: "success", sentence: "Paid." };
    }
    case OrderStatusEnum.PendingApproval:
      return {
        title: "Needs your approval",
        tone: "warning",
        sentence: failedItems.length > 0
          ? `Held because ${heldBy}: ${summarizeReasons(failedText, [])}.`
          : why ? `Held: ${why}` : "Held for your approval. Nothing is charged until you decide.",
      };
    case OrderStatusEnum.Voided:
    case OrderStatusEnum.Rejected:
      return {
        title: "Blocked",
        tone: "danger",
        sentence: why ? `Blocked: ${why}` : "Blocked before payment. You were not charged.",
      };
    case OrderStatusEnum.Failed:
      return {
        title: "Failed",
        tone: "danger",
        sentence: why ? `Failed: ${why}` : "The payment could not be completed.",
      };
    case OrderStatusEnum.AwaitingPayment:
      return {
        title: "Pay in PayPal",
        tone: "warning",
        sentence: "Approve the payment in PayPal first. Sepilo checks the order after that.",
      };
    case OrderStatusEnum.Refunded:
      return { title: "Refunded", tone: "brand", sentence: "This order was paid and then refunded." };
    default:
      return {
        title: "Checking",
        tone: "brand",
        sentence: "Sepilo is running its checks. This page updates by itself.",
      };
  }
}

export function isInProgress(status: OrderStatusEnum): boolean {
  return (
    status === OrderStatusEnum.Received ||
    status === OrderStatusEnum.Authorized ||
    status === OrderStatusEnum.Checking
  );
}
