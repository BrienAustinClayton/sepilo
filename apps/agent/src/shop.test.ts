import assert from "node:assert/strict";
import { generateKeyPairSync } from "node:crypto";
import { beforeEach, test } from "node:test";
import { withEnv } from "./config.ts";
import { newRunContext, runWith } from "./context.ts";
import { LlmLimitError } from "./llm.ts";
import { ShopFailure, shop } from "./shop.ts";

const key = generateKeyPairSync("ed25519").privateKey.export({ format: "jwk" }).d as string;
const ENV = {
  LLM_FAST_BASE_URL: "https://llm.test/v1", LLM_FAST_API_KEY: "k", LLM_FAST_MODEL: "main-model",
  LLM_FAST_FALLBACK_MODEL: "backup-model", CHANNEL3_API_KEY: "c3", INTENTLOCK_API_URL: "https://api.test",
  INTENTLOCK_SIGN_BASE_URL: "https://api.test", AGENT_ID: "agt_test", AGENT_PRIVATE_KEY: key,
};

const product = (id: string, title: string, price: number, domain = "walmart.com", top = "electronics") => ({
  id, title, brands: [{ name: "Acme" }], category: { slug: top, title: top, path: [{ slug: top, title: top }] },
  offers: [{ url: `https://buy.trychannel3.com/${id}`, domain, price: { price, currency: "USD" }, availability: "InStock" }],
});

type Reply = { plan: unknown; choose?: unknown; products: unknown[]; limited?: string[] };
let calls: { url: string; body: any }[];
function fakeFetch(r: Reply) {
  calls = [];
  globalThis.fetch = (async (input: any, init?: any) => {
    const url = String(input);
    const body = init?.body ? JSON.parse(init.body) : undefined;
    calls.push({ url, body });
    const json = (o: unknown, status = 200) => new Response(JSON.stringify(o), { status, headers: { "content-type": "application/json" } });
    if (url.endsWith("/chat/completions")) {
      if (r.limited?.includes(body.model)) return json({ error: "rate" }, 429);
      const isPlan = body.messages[0].content.startsWith("You turn");
      return json({ choices: [{ message: { content: JSON.stringify(isPlan ? r.plan : r.choose) } }] });
    }
    if (url === "https://api.trychannel3.com/v1/search") return json({ products: r.products });
    if (url === "https://api.test/checkout") return json({ order_id: "ord_1", status: "captured", decision: "capture", reasons: [] });
    return new Response("<html></html>", { status: 200 });
  }) as typeof fetch;
}
const run = () => withEnv(ENV, () => runWith(newRunContext("int_1"), () => shop("int_1", "A USB-C cable under $20")));

beforeEach(() => (calls = []));

test("picks a real Channel3 product and checks out with its domain and category", async () => {
  fakeFetch({
    plan: { query: "usb c cable", max_unit_price: 20, quantity: 1 },
    choose: { choice: 1, quantity: 1, reason: "Exact match under budget." },
    products: [product("p0", "USB-C Cable Costume", 9.99), product("p1", "USB-C to USB-C Cable 1m", 12.5, "www.target.com"), product("p2", "Pricey cable", 35)],
  });
  const out = await run();
  assert.equal(out.checkout?.order_id, "ord_1");
  const search = calls.find((c) => c.url.includes("trychannel3"))!.body;
  assert.deepEqual(search.filters, { availability: ["InStock"], price: { max_price: 20 } });
  const checkout = calls.find((c) => c.url === "https://api.test/checkout")!.body;
  assert.equal(checkout.merchant, "target.com");
  assert.equal(checkout.cart[0].category, "electronics");
  assert.equal(checkout.cart[0].unit_price, "12.50");
  const choosePrompt = calls.filter((c) => c.url.endsWith("/chat/completions"))[1].body.messages[1].content;
  assert.ok(!choosePrompt.includes("Pricey cable"), "over-budget items never reach the model");
});

test("fails with the model's reason when nothing fits", async () => {
  fakeFetch({
    plan: { query: "chocolate bar", max_unit_price: 2, quantity: 1 },
    choose: { choice: null, reason: "Only candy molds and costumes were found, no actual chocolate." },
    products: [product("m1", "Chocolate Bar Silicone Mold", 1.19, "hobbylobby.com", "home-garden")],
  });
  await assert.rejects(run(), (e: unknown) => e instanceof ShopFailure && /candy molds/.test((e as Error).message));
  assert.ok(!calls.some((c) => c.url.endsWith("/checkout")));
});

test("over budget names the cheapest offer", async () => {
  let n = 0;
  fakeFetch({ plan: { query: "office chair", max_unit_price: 20, quantity: 1 }, products: [] });
  const base = globalThis.fetch;
  globalThis.fetch = (async (input: any, init?: any) => {
    if (String(input).includes("trychannel3") && n++ > 0) {
      return new Response(JSON.stringify({ products: [product("c1", "Office Chair", 190.49, "overstock.com", "furniture")] }), { status: 200 });
    }
    return base(input, init);
  }) as typeof fetch;
  await assert.rejects(run(), (e: unknown) => e instanceof ShopFailure && /cheapest is \$190\.49 at overstock\.com/.test((e as Error).message));
});

test("rate limit on the main model falls back, then reports the limit", async () => {
  fakeFetch({
    plan: { query: "usb c cable", max_unit_price: null, quantity: 1 },
    choose: { choice: 0, quantity: 1 },
    products: [product("p1", "USB-C Cable", 12.5)],
    limited: ["main-model"],
  });
  assert.equal((await run()).checkout?.order_id, "ord_1");
  assert.ok(calls.some((c) => c.body?.model === "backup-model"));
  fakeFetch({ plan: {}, products: [], limited: ["main-model", "backup-model"] });
  await assert.rejects(run(), (e: unknown) => e instanceof LlmLimitError);
});

test("approved cart: one store, exact items, current Channel3 prices", async () => {
  const items: Record<string, unknown> = {
    a: product("a", "USB-C Cable", 9.99, "baseus.com"),
    b: product("b", "USB-C Hub", 24.5, "baseus.com"),
    c: product("c", "Mouse", 15, "target.com"),
  };
  let checkout: any;
  globalThis.fetch = (async (input: any, init?: any) => {
    const url = String(input);
    if (url.startsWith("https://api.trychannel3.com/v1/products/")) {
      const id = decodeURIComponent(url.split("/").pop()!);
      return new Response(JSON.stringify(items[id]), { status: items[id] ? 200 : 404 });
    }
    if (url === "https://api.test/checkout") {
      checkout = JSON.parse(init.body);
      return new Response(JSON.stringify({ order_id: "ord_2", status: "captured", decision: "capture", reasons: [] }), { status: 200 });
    }
    return new Response("<html></html>", { status: 200 });
  }) as typeof fetch;
  const { shopExact } = await import("./shop.ts");
  const buy = (picks: { productId: string; qty: number }[]) =>
    withEnv(ENV, () => runWith(newRunContext("int_1"), () => shopExact("int_1", picks)));
  const out = await buy([{ productId: "a", qty: 2 }, { productId: "b", qty: 1 }]);
  assert.equal(out.checkout?.order_id, "ord_2");
  assert.equal(checkout.merchant, "baseus.com");
  assert.deepEqual(checkout.cart.map((l: any) => [l.product_id, l.qty, l.unit_price]), [["a", 2, "9.99"], ["b", 1, "24.50"]]);
  assert.match(out.summary, /Bought 3 items from baseus.com for \$44\.48/);
  await assert.rejects(buy([{ productId: "a", qty: 1 }, { productId: "c", qty: 1 }]), /different stores/);
  await assert.rejects(buy([{ productId: "gone", qty: 1 }]), /no longer available/);
});
