import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";
import { resetChannel3Guards } from "./channel3Guard.ts";
import { withEnv } from "./config.ts";
import { OFF_TOPIC_REPLY, suggest, type Rule } from "./suggest.ts";

const ENV = { LLM_FAST_BASE_URL: "https://llm.test/v1", LLM_FAST_API_KEY: "k", LLM_FAST_MODEL: "m", CHANNEL3_API_KEY: "c3" };
const prod = (id: string, title: string, price: number, domain: string, top: string) => ({
  id, title, images: [{ url: `https://img.test/${id}.png` }], category: { slug: top, title: top, path: [{ slug: top, title: top }] },
  offers: [{ url: `https://buy.test/${id}`, domain, price: { price, currency: "USD" } }],
});

let calls: any[] = [];
beforeEach(() => resetChannel3Guards({ noSleep: true })); // each test has its own fake catalog
function fake(plan: unknown, pick: unknown, products: unknown[]) {
  calls = [];
  globalThis.fetch = (async (input: any, init?: any) => {
    const url = String(input);
    const body = init?.body ? JSON.parse(init.body) : undefined;
    calls.push({ url, body });
    const json = (o: unknown) => new Response(JSON.stringify(o), { status: 200 });
    if (url.endsWith("/chat/completions")) {
      const isPlan = body.messages[0].content.startsWith("You are Sepilo");
      return json({ choices: [{ message: { content: JSON.stringify(isPlan ? plan : pick) } }] });
    }
    return json({ products });
  }) as typeof fetch;
}
const rules: Rule[] = [{ categories: ["electronics"], merchants: ["*"], remaining: "30.00", currency: "USD" }];
const run = (msg: string, r = rules) => withEnv(ENV, () => suggest(msg, [{ role: "user", content: "hi" }], r));

test("small talk does not search", async () => {
  fake({ topic: "greeting", search: false, reply: "Hi! What should I find for you?" }, null, []);
  const out = await run("hello");
  assert.equal(out.products.length, 0);
  assert.match(out.reply, /What should I find/);
  assert.ok(!calls.some((c) => c.url.includes("trychannel3")));
});

test("filters by rules before the model and returns picks with images", async () => {
  fake(
    { topic: "shopping", search: true, query: "usb c cable", max_unit_price: null, quantity: 1 },
    { picks: [1, 0, 9], reply: "Two good cables from $9.99." },
    [
      prod("a", "USB-C Cable A", 12, "target.com", "electronics"),
      prod("b", "USB-C Cable B", 9.99, "baseus.com", "electronics"),
      prod("c", "Cable costume", 8, "costumes.com", "apparel-accessories"),
      prod("d", "Pricey cable", 45, "dell.com", "electronics"),
    ],
  );
  const out = await run("usb c cable");
  const search = calls.find((c) => c.url.includes("trychannel3")).body;
  assert.equal(search.filters.price.max_price, 30);
  const pickPrompt = calls.filter((c) => c.url.endsWith("/chat/completions"))[1].body.messages[1].content;
  assert.ok(!pickPrompt.includes("costume") && !pickPrompt.includes("Pricey"));
  assert.deepEqual(out.products.map((p) => p.product_id), ["b", "a"]);
  assert.equal(out.products[0].image, "https://img.test/b.png");
  assert.equal(out.products[0].merchant, "baseus.com");
});

test("explains when nothing fits the rules", async () => {
  fake({ topic: "shopping", search: true, query: "office chair", quantity: 1 }, null, [prod("f", "Office Chair", 25, "overstock.com", "furniture")]);
  const out = await run("office chair");
  assert.equal(out.products.length, 0);
  assert.match(out.reply, /none fit your spending rules: they're in furniture/);
  const storeOnly: Rule[] = [{ categories: ["furniture"], merchants: ["ikea.com"], remaining: "30.00", currency: "USD" }];
  fake({ topic: "shopping", search: true, query: "office chair", quantity: 1 }, null, [prod("f", "Office Chair", 25, "overstock.com", "furniture")]);
  assert.match((await run("office chair", storeOnly)).reply, /from stores your rules don't allow/);
});

test("no budget left means no search", async () => {
  fake({ topic: "shopping", search: true, query: "cable", quantity: 1 }, null, []);
  const out = await run("cable", [{ ...rules[0], remaining: "0.00" }]);
  assert.match(out.reply, /budget is used up/);
  assert.ok(!calls.some((c) => c.url.includes("trychannel3")));
});


test("off-topic questions get a fixed reply, never a model answer", async () => {
  for (const plan of [
    { topic: "off_topic", search: false, reply: "Paris is the capital of France." },
    { search: false, reply: "Here is a poem about the sea..." }, // unlabelled: treated as off-topic
    { topic: "off_topic", search: true, query: "capital of france" },
  ]) {
    fake(plan, null, []);
    const out = await run("what is the capital of France?");
    assert.equal(out.reply, OFF_TOPIC_REPLY);
    assert.equal(out.products.length, 0);
    assert.ok(!calls.some((c) => c.url.includes("trychannel3")), "no Channel3 credits spent");
  }
});

test("the plan prompt limits Sepilo to shopping", async () => {
  fake({ topic: "greeting", search: false, reply: "Hi!" }, null, []);
  await run("hello");
  const system = calls.find((c) => c.url.endsWith("/chat/completions")).body.messages[0].content;
  assert.match(system, /only help with shopping/);
  assert.match(system, /off_topic/);
});

const multi = (id: string, title: string, top: string, offers: [string, number][]) => ({
  ...prod(id, title, offers[0][1], offers[0][0], top),
  offers: offers.map(([domain, price]) => ({ url: `https://${domain}/${id}`, domain, price: { price, currency: "USD" }, availability: "InStock" })),
});
const plan = { topic: "shopping", search: true, query: "usb c cable", max_unit_price: null, quantity: 1 };

test("picks the cheapest store the rules allow and shows the saving", async () => {
  fake(plan, { picks: [0], reply: "Best price across 3 stores." }, [
    multi("a", "USB-C Cable A", "electronics", [["target.com", 14], ["baseus.com", 9.5], ["dell.com", 18.25]]),
  ]);
  const out = await run("usb c cable");
  assert.equal(out.products[0].merchant, "baseus.com");
  assert.equal(out.products[0].price, "9.50");
  assert.equal(out.products[0].url, "https://baseus.com/a");
  assert.equal(out.products[0].compare_price, "18.25");
  assert.equal(out.products[0].store_count, 3);
  const pickPrompt = calls.filter((c) => c.url.endsWith("/chat/completions"))[1].body.messages[1].content;
  assert.match(pickPrompt, /\$9\.50 \| baseus\.com .*cheapest of 3 stores/);
});

test("skips a cheaper store the rules do not allow", async () => {
  const onlyTarget: Rule[] = [{ categories: ["electronics"], merchants: ["target.com"], remaining: "30.00", currency: "USD" }];
  fake(plan, { picks: [0], reply: "ok" }, [
    multi("a", "USB-C Cable A", "electronics", [["baseus.com", 9.5], ["target.com", 14], ["dell.com", 18.25]]),
  ]);
  const out = await run("usb c cable", onlyTarget);
  assert.equal(out.products[0].merchant, "target.com");
  assert.equal(out.products[0].price, "14.00");
  assert.equal(out.products[0].compare_price, "18.25");
  assert.equal(out.products[0].store_count, 3);
});

test("no comparison price with a single store", async () => {
  fake(plan, { picks: [0], reply: "ok" }, [prod("a", "USB-C Cable A", 12, "target.com", "electronics")]);
  const out = await run("usb c cable");
  assert.equal(out.products[0].compare_price, null);
  assert.equal(out.products[0].store_count, 1);
  resetChannel3Guards({ noSleep: true });
  fake(plan, { picks: [0], reply: "ok" }, [multi("b", "USB-C Cable B", "electronics", [["target.com", 12], ["dell.com", 12]])]);
  const same = await run("usb c cable");
  assert.equal(same.products[0].compare_price, null);
  assert.equal(same.products[0].store_count, 2);
});
