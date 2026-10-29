import { createShoppingAgent } from "./agent.ts";
import { agentId } from "./config.ts";
import { newRunContext, runWith, type CartLine, type CheckoutResult } from "./context.ts";
import { Channel3Unavailable } from "./channel3Guard.ts";
import { ApiError, getIntent } from "./intentlock.ts";
import { LlmLimitError } from "./llm.ts";
import { ShopFailure, shop, shopExact, type ExactPick } from "./shop.ts";

export interface RunResult {
  intent_id: string;
  request_text: string;
  trace_id: string;
  order_id: string | null;
  status: string | null;
  decision: string | null;
  reasons: string[];
  cart: CartLine[];
  total: string | null;
  summary: string;
  errors: string[];
}

const inflight = new Map<string, Promise<RunResult>>();

/** One shopping run for a signed intent. Concurrent calls for the same intent share one run (no double checkout). */
export function runShopping(intentId: string, exact?: ExactPick[]): Promise<RunResult> {
  if (!/^int_[A-Za-z0-9_]{1,60}$/.test(intentId)) return Promise.reject(new RunError(400, "invalid intent_id"));
  const existing = inflight.get(intentId);
  if (existing) return existing;
  const p = doRun(intentId, exact).finally(() => inflight.delete(intentId));
  inflight.set(intentId, p);
  return p;
}

export class RunError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function doRun(intentId: string, exact?: ExactPick[]): Promise<RunResult> {
  let intent;
  try {
    intent = await getIntent(intentId);
  } catch (e) {
    const status = (e as { status?: number }).status;
    if (status === 404) throw new RunError(404, "intent not found");
    throw new RunError(502, `could not read intent: ${(e as Error).message}`);
  }
  if (intent.agent_id !== agentId()) throw new RunError(403, "intent belongs to a different agent");

  const ctx = newRunContext(intentId);
  let summary: string;
  try {
    const go = exact?.length ? () => shopExact(intent.id, exact) : () => shop(intent.id, intent.request_text);
    summary = (await runWith(ctx, go)).summary;
  } catch (e) {
    if (e instanceof ShopFailure) summary = e.message;
    else if (e instanceof LlmLimitError) summary = "The AI model's usage limit is reached for now. Try again later.";
    else if (e instanceof Channel3Unavailable) summary = e.message;
    else if (e instanceof ApiError && e.reason && !ctx.checkouts.length) {
      ctx.errors.push(e.message.slice(0, 300));
      summary = `The agent couldn't check out: ${e.reason.slice(0, 300)}`;
    } else {
      ctx.errors.push((e as Error).message.slice(0, 300));
      summary = ctx.checkouts.length ? "Checked out, but the run ended with an error." : `The agent couldn't check out: ${(e as Error).message.slice(0, 200)}`;
    }
  }
  const co: CheckoutResult | undefined = ctx.checkouts[0];
  return {
    intent_id: intent.id,
    request_text: intent.request_text,
    trace_id: ctx.traceId,
    order_id: co?.order_id ?? null,
    status: co?.status ?? null,
    decision: co?.decision ?? null,
    reasons: co?.reasons ?? [],
    cart: ctx.lastCart?.cart ?? [],
    total: ctx.lastCart?.total ?? null,
    summary: summary.slice(0, 2000),
    errors: ctx.errors,
  };
}

/** Cart draft from free text: same agent, no checkout tool. Used by the smoke script. */
export async function runDraft(requestText: string): Promise<Pick<RunResult, "trace_id" | "cart" | "total" | "summary"> & { merchant: string | null }> {
  const ctx = newRunContext();
  const agent = createShoppingAgent({ draft: true });
  const prompt =
    `The user's request (this is the whole task):\n<user_request>\n${requestText}\n</user_request>\n` +
    `Find the items and call build_cart. This is a draft: there is no checkout tool. Then summarise the cart.`;
  const result = await runWith(ctx, () =>
    agent.generate(prompt, { maxSteps: 14, modelSettings: { temperature: 0.2 }, tracingOptions: { traceId: ctx.traceId } }),
  );
  return {
    trace_id: ctx.traceId,
    merchant: ctx.lastCart?.merchant ?? null,
    cart: ctx.lastCart?.cart ?? [],
    total: ctx.lastCart?.total ?? null,
    summary: String(result.text ?? "").slice(0, 2000),
  };
}
