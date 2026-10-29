import { NextResponse, type NextRequest } from "next/server";
import { SESSION_COOKIE, callApi, clearSession, relay } from "@/lib/server/auth";

export async function GET(req: NextRequest) {
  const token = req.cookies.get(SESSION_COOKIE)?.value;
  if (!token) return NextResponse.json({ error: "unauthenticated", reason: "Sign in required." }, { status: 401 });
  const { status, data } = await callApi(`/disputes${req.nextUrl.search}`, { method: "GET", token });
  const res = relay(status, data);
  if (status === 401) clearSession(res);
  return res;
}
