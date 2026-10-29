import { NextResponse, type NextRequest } from "next/server";
import { SESSION_COOKIE, callApi, clearSession, forbidden, relay, sameOrigin } from "@/lib/server/auth";

const SEGMENT = /^[A-Za-z0-9_-]{1,80}$/;

async function forward(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  if (req.method !== "GET" && !sameOrigin(req)) return forbidden();
  const token = req.cookies.get(SESSION_COOKIE)?.value;
  if (!token) return NextResponse.json({ error: "unauthenticated", reason: "Sign in required." }, { status: 401 });
  const { path } = await ctx.params;
  if (!path.every((p) => SEGMENT.test(p))) return NextResponse.json({ error: "not_found" }, { status: 404 });
  const body = req.method === "GET" ? undefined : await req.json().catch(() => ({}));
  const { status, data } = await callApi(`/me/${path.join("/")}${req.nextUrl.search}`, {
    method: req.method,
    body,
    token,
  });
  const res = relay(status, data);
  if (status === 401) clearSession(res);
  return res;
}

export { forward as GET, forward as POST, forward as PUT, forward as PATCH, forward as DELETE };
