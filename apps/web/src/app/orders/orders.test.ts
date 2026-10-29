/**
 * Unit tests for wallet orders decimal math helpers.
 * Run with: node --experimental-strip-types --test src/app/orders/orders.test.ts
 */
import { strict as assert } from "node:assert";
import { test } from "node:test";

// -----------------------------------------------------------------------
// lineTotal — integer cent math, no float drift
// Mirrors the implementation in OrderDetailClient.tsx
// -----------------------------------------------------------------------

function lineTotal(unitPrice: string, qty: number): string {
  const parts = unitPrice.split(".");
  const wholePart = parseInt(parts[0] ?? "0", 10);
  const fracStr = (parts[1] ?? "").padEnd(2, "0").slice(0, 2);
  const fracPart = parseInt(fracStr, 10);
  const priceCents = wholePart * 100 + fracPart;
  const totalCents = priceCents * qty;
  const d = Math.floor(totalCents / 100);
  const c = totalCents % 100;
  return `${d}.${String(c).padStart(2, "0")}`;
}

test("orders: lineTotal basic cases", () => {
  assert.equal(lineTotal("9.99", 2), "19.98");
  assert.equal(lineTotal("10.00", 3), "30.00");
  assert.equal(lineTotal("1.50", 4), "6.00");
  assert.equal(lineTotal("0.99", 1), "0.99");
  assert.equal(lineTotal("100.00", 1), "100.00");
});

test("orders: lineTotal no float drift", () => {
  // 9.99 * 3 in float = 29.970000000000002; must be 29.97
  assert.equal(lineTotal("9.99", 3), "29.97");
  // 7.50 * 7 = 52.50
  assert.equal(lineTotal("7.50", 7), "52.50");
  // 19.99 * 5 = 99.95
  assert.equal(lineTotal("19.99", 5), "99.95");
});

test("orders: lineTotal zero quantity", () => {
  assert.equal(lineTotal("9.99", 0), "0.00");
});

test("orders: lineTotal missing decimal", () => {
  // "10" treated as "10.00"
  assert.equal(lineTotal("10", 2), "20.00");
});

const constantsUrl = new URL("../../features/orders/constants.ts", import.meta.url).href;
const constants: Record<string, unknown> = await import(constantsUrl);

function records(value: unknown): Record<string, unknown>[] {
  assert.ok(Array.isArray(value));
  return value.filter((v): v is Record<string, unknown> => typeof v === "object" && v !== null);
}

test("checks guide: all 32 checks are explained in full", () => {
  const info = constants.CHECK_INFO;
  assert.ok(typeof info === "object" && info !== null);
  const ids = Array.from({ length: 32 }, (_, i) => `P${String(i + 1).padStart(2, "0")}`);
  assert.deepEqual(Object.keys(info).sort(), ids);
  for (const entry of Object.values(info)) {
    assert.ok(typeof entry === "object" && entry !== null);
    for (const field of ["label", "what", "why", "onFail"]) {
      const text: unknown = Reflect.get(entry, field);
      assert.ok(typeof text === "string" && text.length > 0, field);
    }
  }
});

test("checks guide: 10 groups cover every check exactly once", () => {
  const groups = records(constants.CHECK_GROUPS);
  assert.equal(groups.length, 10);
  const covered: number[] = [];
  for (const g of groups) {
    const { from, to } = g;
    assert.ok(typeof from === "number" && typeof to === "number");
    for (let n = from; n <= to; n++) covered.push(n);
  }
  assert.deepEqual(covered, Array.from({ length: 32 }, (_, i) => i + 1));
});
