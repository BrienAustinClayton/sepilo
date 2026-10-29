/**
 * Plain Node entry (`pnpm --filter agent start`) and the HTTP trigger used on Astropods too.
 *   POST /run {"intent_id":"int_..."}  -> run the shopping agent for that signed intent
 *   GET  /health
 */
import { createServer, type Server } from "node:http";
import { fileURLToPath } from "node:url";
import { timingSafeEqual } from "node:crypto";
import { env, withEnv } from "./config.ts";
import { emit } from "./log.ts";
import { Channel3Unavailable } from "./channel3Guard.ts";
import { LlmLimitError } from "./llm.ts";
import { RunError, runShopping, type RunResult } from "./run.ts";
import type { ExactPick, WebSnapshot } from "./shop.ts";
import { suggest, type Rule, type Turn } from "./suggest.ts";

function authorized(header: string | undefined): boolean {
  const secret = env("AGENT_RUN_SECRET");
  if (!secret || !header?.startsWith("Bearer ")) return false;
  const given = Buffer.from(header.slice(7));
  const want = Buffer.from(secret);
  return given.length === want.length && timingSafeEqual(given, want);
}

async function readJson(req: import("node:http").IncomingMessage, limit: number): Promise<unknown | undefined> {
  const chunks: Buffer[] = [];
  let size = 0;
  for await (const c of req) {
    size += (c as Buffer).length;
    if (size > limit) return undefined;
    chunks.push(c as Buffer);
  }
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}");
  } catch {
    return undefined;
  }
}

function webSnapshot(v: unknown): WebSnapshot | undefined {
  if (typeof v !== "object" || v === null) return undefined;
  const s = v as Record<string, unknown>;
  const text = (x: unknown, max: number) => (typeof x === "string" && x.length > 0 && x.length <= max ? x : null);
  const title = text(s.title, 300);
  const merchant = text(s.merchant, 64);
  const category = text(s.category, 64);
  const url = text(s.url, 2048);
  const price = text(s.price, 14);
  if (!title || !merchant || !category || !url || !price || !url.startsWith("https://") || !/^\d{1,9}\.\d{2}$/.test(price)) {
    return undefined;
  }
  return { title, price, merchant, url, category };
}

export function startServer(port = Number(env("PORT") ?? 8808), host = env("HOST") ?? "127.0.0.1"): Server {
  const server = createServer(async (req, res) => {
    const send = (status: number, body: unknown) => {
      res.writeHead(status, { "Content-Type": "application/json" });
      res.end(JSON.stringify(body));
    };
    const runId = typeof req.headers["x-intentlock-run"] === "string" ? req.headers["x-intentlock-run"].slice(0, 64) : undefined;
    let intentId: unknown;
    try {
      const path = (req.url ?? "").split("?")[0];
      if (req.method === "GET" && path === "/health") return send(200, { ok: true });
      // Uptime / keep-awake cron: always 200, no model or Channel3 calls.
      if ((req.method === "GET" || req.method === "HEAD") && path === "/ping") return send(200, { ok: true });
      if (req.method === "POST" && path === "/suggest") {
        if (!authorized(req.headers.authorization)) return send(401, { reason: "unauthorized" });
        const raw = await readJson(req, 40_000);
        if (raw === undefined) return send(400, { reason: "invalid JSON" });
        const { message, history, rules } = raw as { message?: unknown; history?: unknown; rules?: unknown };
        if (typeof message !== "string" || !message.trim() || message.length > 1000) return send(400, { reason: "message required" });
        const turns: Turn[] = (Array.isArray(history) ? history : [])
          .filter((t: any) => (t?.role === "user" || t?.role === "assistant") && typeof t?.content === "string")
          .slice(-8)
          .map((t: any) => ({ role: t.role, content: String(t.content).slice(0, 1200) }));
        const ruleList: Rule[] = (Array.isArray(rules) ? rules : [])
          .filter((r: any) => Array.isArray(r?.categories) && Array.isArray(r?.merchants) && /^\d{1,9}\.\d{2}$/.test(String(r?.remaining)))
          .slice(0, 20)
          .map((r: any) => ({
            categories: r.categories.map(String).slice(0, 50), merchants: r.merchants.map(String).slice(0, 50),
            remaining: String(r.remaining), currency: String(r.currency ?? "USD"),
          }));
        const t0 = Date.now();
        try {
          const out = await suggest(message, turns, ruleList);
          emit("suggest.finished", { agent_id: (raw as any).agent_id, ms: Date.now() - t0, products: out.products.length });
          return send(200, out);
        } catch (e) {
          emit("suggest.error", { agent_id: (raw as any).agent_id, reason: (e as Error).message.slice(0, 300) });
          if (e instanceof Channel3Unavailable) return send(200, { reply: e.message, products: [] });
          if (e instanceof LlmLimitError) {
            return send(200, { reply: "I've hit my AI usage limit for the moment. Please try again in a little while.", products: [] });
          }
          return send(200, { reply: "Something went wrong while searching. Please try again.", products: [] });
        }
      }
      if (req.method === "POST" && path === "/run") {
        const parsed = await readJson(req, 10_000);
        if (parsed === undefined) return send(400, { reason: "invalid JSON" });
        const body = parsed as {
          intent_id?: unknown; agent_id?: unknown; agent_private_key?: unknown; product_id?: unknown; qty?: unknown; items?: unknown;
        };
        intentId = body.intent_id;
        const hosted = body.agent_id !== undefined || body.agent_private_key !== undefined;
        emit("run.received", { run_id: runId, intent_id: intentId, agent_id: body.agent_id, hosted });
        if (typeof intentId !== "string") return send(400, { reason: "intent_id required" });
        const id = intentId;
        const t0 = Date.now();
        const finish = (r: RunResult) => {
          emit("run.finished", {
            run_id: runId, intent_id: id, ms: Date.now() - t0, order_id: r.order_id,
            status: r.status, decision: r.decision, outcome: r.order_id ? "ordered" : "no_order", summary: r.summary?.slice(0, 200),
          });
          return send(200, r);
        };
        if (!hosted) return finish(await runShopping(id));
        // Hosted run for a user's agent: only the IntentLock API may hand over agent credentials.
        if (!authorized(req.headers.authorization)) {
          emit("run.rejected", { run_id: runId, intent_id: intentId, reason: "unauthorized" });
          return send(401, { reason: "unauthorized" });
        }
        if (typeof body.agent_id !== "string" || !/^agt_[A-Za-z0-9_]{1,60}$/.test(body.agent_id)) {
          return send(400, { reason: "invalid agent_id" });
        }
        if (typeof body.agent_private_key !== "string" || body.agent_private_key.length > 64) {
          return send(400, { reason: "invalid agent_private_key" });
        }
        const rawItems: unknown[] | undefined = Array.isArray(body.items)
          ? body.items
          : body.product_id !== undefined ? [{ product_id: body.product_id, qty: body.qty ?? 1 }] : undefined;
        let exact: ExactPick[] | undefined;
        if (rawItems) {
          if (rawItems.length < 1 || rawItems.length > 10) return send(400, { reason: "invalid items" });
          exact = [];
          for (const it of rawItems as { product_id?: unknown; qty?: unknown; snapshot?: unknown }[]) {
            const qty = Number(it?.qty ?? 1);
            if (typeof it?.product_id !== "string" || it.product_id.length > 128 || !Number.isInteger(qty) || qty < 1 || qty > 20) {
              return send(400, { reason: "invalid product_id or qty" });
            }
            const snapshot = webSnapshot(it.snapshot);
            if (it.product_id.startsWith("web_") && !snapshot) return send(400, { reason: "invalid web snapshot" });
            exact.push({ productId: it.product_id, qty, snapshot });
          }
        }
        const creds = { AGENT_ID: body.agent_id, AGENT_PRIVATE_KEY: body.agent_private_key };
        return finish(await withEnv(creds, () => runShopping(id, exact)));
      }
      send(404, { reason: "not found" });
    } catch (e) {
      const message = (e as Error).message ?? "";
      const status = e instanceof RunError ? e.status : /rate limit|quota|429/i.test(message) ? 503 : 500;
      emit("run.error", { run_id: runId, intent_id: intentId, status, reason: message.slice(0, 300) });
      if (e instanceof RunError) return send(e.status, { reason: e.message });
      if (status === 503) {
        return send(503, { reason: "the AI model's usage limit is reached for now; try again later" });
      }
      send(500, { reason: "agent run failed" });
    }
  });
  server.listen(port, host, () => console.log(`intentlock agent listening on http://${host}:${port} (POST /run)`));
  return server;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) startServer();
