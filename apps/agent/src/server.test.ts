import assert from "node:assert/strict";
import type { AddressInfo } from "node:net";
import { after, before, test } from "node:test";
import { agentId, env, withEnv } from "./config.ts";
import { startServer } from "./server.ts";

test("withEnv overrides agent credentials only inside the run", async () => {
  const outside = agentId();
  const inside = await withEnv({ AGENT_ID: "agt_user_x", AGENT_PRIVATE_KEY: "k" }, async () => {
    await new Promise((r) => setTimeout(r, 5));
    return [agentId(), env("AGENT_PRIVATE_KEY")];
  });
  assert.deepEqual(inside, ["agt_user_x", "k"]);
  assert.equal(agentId(), outside);
});

let base = "";
let server: ReturnType<typeof startServer>;
before(async () => {
  process.env.AGENT_RUN_SECRET = "s3cret-value";
  server = startServer(0, "127.0.0.1");
  await new Promise((r) => server.once("listening", r));
  base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
});
after(() => server.close());

const run = (body: unknown, auth?: string) =>
  fetch(`${base}/run`, {
    method: "POST",
    headers: { "content-type": "application/json", ...(auth ? { authorization: auth } : {}) },
    body: JSON.stringify(body),
  });

test("hosted run with agent credentials needs the run secret", async () => {
  const body = { intent_id: "int_x", agent_id: "agt_x", agent_private_key: "k" };
  assert.equal((await run(body)).status, 401);
  assert.equal((await run(body, "Bearer wrong")).status, 401);
  assert.equal((await run({ ...body, agent_id: "nope" }, "Bearer s3cret-value")).status, 400);
});

test("web deal items need a valid snapshot", async () => {
  const body = { intent_id: "int_x", agent_id: "agt_x", agent_private_key: "k" };
  const snapshot = { title: "Cable", price: "12.99", merchant: "shop.test", url: "https://www.shop.test/p", category: "electronics" };
  const rejected = async (snap?: unknown) => {
    const res = await run({ ...body, items: [{ product_id: "web_abc", qty: 1, snapshot: snap }] }, "Bearer s3cret-value");
    return [res.status, (await res.json()).reason];
  };
  assert.deepEqual(await rejected(), [400, "invalid web snapshot"]);
  assert.deepEqual(await rejected({ ...snapshot, price: "12.9" }), [400, "invalid web snapshot"]);
  assert.deepEqual(await rejected({ ...snapshot, url: "http://shop.test/p" }), [400, "invalid web snapshot"]);
});

test("ping answers cron jobs without credentials", async () => {
  const server = startServer(0, "127.0.0.1");
  await new Promise((r) => server.once("listening", r));
  const { port } = server.address() as { port: number };
  try {
    const res = await fetch(`http://127.0.0.1:${port}/ping`);
    assert.equal(res.status, 200);
    assert.deepEqual(await res.json(), { ok: true });
    assert.equal((await fetch(`http://127.0.0.1:${port}/ping`, { method: "HEAD" })).status, 200);
  } finally {
    server.close();
  }
});
