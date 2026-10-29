"use client";

import { useEffect, useState } from "react";

export type Me = {
  id: string;
  email: string | null;
  name: string;
  avatar_url: string | null;
  country: string | null;
  currency: string | null;
  company: string | null;
  onboarding: Record<string, unknown> | null;
  next: "signup" | "onboarding" | "app";
  has_address?: boolean;
  role: "user" | "dispute_manager";
};

let pending: Promise<Me | null> | null = null;

export function fetchMe(): Promise<Me | null> {
  pending ??= fetch("/api/auth/me", { cache: "no-store" })
    .then((r) => (r.ok ? (r.json() as Promise<Me>) : null))
    .catch(() => null);
  return pending;
}

export function resetMe() {
  pending = null;
}

export function useMe(): Me | null {
  const [me, setMe] = useState<Me | null>(null);
  useEffect(() => {
    let live = true;
    fetchMe().then((m) => live && setMe(m));
    return () => {
      live = false;
    };
  }, []);
  return me;
}

export async function signOut() {
  await fetch("/api/auth/logout", { method: "POST" }).catch(() => null);
  pending = null;
  // Full reload on purpose: drops every bit of signed-in client state.
  // eslint-disable-next-line @next/next/no-location-assign-relative-destination
  window.location.assign("/login");
}

export async function postJson(url: string, body: unknown): Promise<{ ok: boolean; data: Record<string, unknown> }> {
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = (await res.json().catch(() => ({}))) as Record<string, unknown>;
    return { ok: res.ok, data };
  } catch {
    return { ok: false, data: { reason: "Network error. Check your connection and try again." } };
  }
}

export function errorText(data: Record<string, unknown>, fallback = "Something went wrong. Try again."): string {
  return typeof data.reason === "string" && data.reason ? data.reason : fallback;
}
