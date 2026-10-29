import { OrderStatusEnum, PreflightStatusEnum, SecurityCheckStepEnum } from "./enums";
import { PreflightItem, PreflightSummary } from "./types";

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
  return date.toLocaleDateString();
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

const TONE = {
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
