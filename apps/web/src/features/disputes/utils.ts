import { CartItemDetails } from "@/features/orders/types";
import { DisputeCartLine } from "./types";

export function shortOrderId(orderId: string): string {
  return orderId.slice(-6).toUpperCase();
}

export function parseTypedAmount(typed: string): number {
  return Number(typed.replace(/[$,\s]/g, ""));
}

export function amountMatches(typed: string, total: string): boolean {
  const expected = Number(total);
  const value = parseTypedAmount(typed);
  return typed.trim().length > 0 && Number.isFinite(value) && Number.isFinite(expected) && Math.round(value * 100) === Math.round(expected * 100);
}

export function toCartItems(lines: DisputeCartLine[] | null): CartItemDetails[] {
  return (lines ?? []).map((line) => ({
    product_id: line.product_id,
    title: line.title ?? line.product_id,
    price: line.unit_price ?? line.price ?? "0",
    qty: line.qty,
    category: line.category ?? "",
  }));
}

export function formatDateTime(isoString: string | null): string {
  if (!isoString) return "";
  const date = new Date(isoString);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString();
}
