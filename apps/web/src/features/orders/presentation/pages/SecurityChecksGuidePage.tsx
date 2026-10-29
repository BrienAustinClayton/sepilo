"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowLeft, ChevronDown, Shield, ShieldCheck, ThumbsUp } from "lucide-react";
import { CHECK_GROUPS, CHECK_INFO, HELD, checkIdsInGroup } from "../../constants";

const FIELD_LABEL = "text-[11px] font-semibold uppercase tracking-wide text-fg-dim";

const ALL_IDS = CHECK_GROUPS.flatMap((group) => checkIdsInGroup(group));

interface CheckRowProps {
  id: string;
  open: boolean;
  onToggle: (id: string) => void;
}

function CheckRow({ id, open, onToggle }: CheckRowProps) {
  const info = CHECK_INFO[id];
  if (!info) return null;
  const panelId = `check-${id}-panel`;
  return (
    <li>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => onToggle(id)}
        className="flex w-full items-start gap-3 px-4 py-2.5 text-left transition hover:bg-fg/5 sm:px-5"
      >
        <Shield className="mt-0.5 h-4 w-4 shrink-0 text-fg-dim" strokeWidth={1.8} aria-hidden="true" />
        <span className="min-w-0 flex-1 space-y-0.5">
          <span className="flex flex-wrap items-center gap-2">
            <span className="rounded-md border border-line px-1.5 py-0.5 font-mono text-[11px] text-fg-dim">{id}</span>
            <span className="text-sm font-medium text-fg">{info.label}</span>
          </span>
          <span className="block text-sm text-fg-muted">{info.what}</span>
        </span>
        <ChevronDown
          className={`mt-0.5 h-4 w-4 shrink-0 text-fg-dim transition-transform ${open ? "rotate-180" : ""}`}
          strokeWidth={1.8}
          aria-hidden="true"
        />
      </button>
      {open && (
        <dl id={panelId} className="space-y-3 px-4 pb-4 pl-11 sm:px-5 sm:pl-12">
          <div className="space-y-1">
            <dt className={FIELD_LABEL}>Why it matters</dt>
            <dd className="text-sm text-fg-2">{info.why}</dd>
          </div>
          {info.onFail !== HELD && (
            <div className="space-y-1">
              <dt className={FIELD_LABEL}>If it fails</dt>
              <dd className="text-sm text-fg-2">{info.onFail}</dd>
            </div>
          )}
        </dl>
      )}
    </li>
  );
}

export function SecurityChecksGuidePage() {
  const [openIds, setOpenIds] = useState<Set<string>>(() => new Set());
  const allOpen = openIds.size === ALL_IDS.length;

  function toggle(id: string) {
    setOpenIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <Link
        href="/orders"
        className="inline-flex items-center gap-1.5 text-xs text-fg-muted hover:text-fg transition"
      >
        <ArrowLeft className="w-3.5 h-3.5" aria-hidden="true" />
        Back to orders
      </Link>

      <header className="space-y-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-xl border border-blue-500/20 bg-blue-500/10 text-blue-400">
          <ShieldCheck className="h-5 w-5" strokeWidth={1.8} aria-hidden="true" />
        </span>
        <h1 className="text-2xl font-semibold tracking-tight">The 32 security checks</h1>
        <p className="text-sm text-fg-2 max-w-2xl">
          Before Sepilo pays for anything, every order must pass these 32 checks.
        </p>
        <div className="saas-card flex items-start gap-3 p-4 text-xs text-fg-muted">
          <ThumbsUp className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" strokeWidth={1.8} aria-hidden="true" />
          <p>
            If any check fails, the payment is held and you decide. The checks are plain code and never spend money on
            their own. The four AI checks (P26 to P29) are warnings you can read and still approve.
          </p>
        </div>
        <nav aria-label="Check groups" className="flex flex-wrap gap-2 pt-1">
          {CHECK_GROUPS.map((group) => (
            <a
              key={group.key}
              href={`#group-${group.key}`}
              className="inline-flex h-8 items-center rounded-full border border-line px-3 text-xs font-medium text-fg-muted transition hover:text-fg"
            >
              {group.title}
            </a>
          ))}
        </nav>
      </header>

      <div className="flex justify-end">
        <button
          type="button"
          onClick={() => setOpenIds(allOpen ? new Set() : new Set(ALL_IDS))}
          className="h-8 px-2 text-xs font-medium text-fg-muted transition hover:text-fg"
        >
          {allOpen ? "Collapse all" : "Expand all"}
        </button>
      </div>

      {CHECK_GROUPS.map((group) => {
        const ids = checkIdsInGroup(group);
        return (
          <section
            key={group.key}
            id={`group-${group.key}`}
            aria-labelledby={`group-${group.key}-title`}
            className="scroll-mt-20 space-y-2"
          >
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 px-1">
              <h2 id={`group-${group.key}-title`} className="text-sm font-semibold text-fg">
                {group.title}
                <span className="ml-2 font-mono text-xs font-normal text-fg-dim">
                  {ids[0]}
                  {ids.length > 1 ? ` to ${ids[ids.length - 1]}` : ""}
                </span>
              </h2>
              <p className="text-xs text-fg-muted">{group.blurb}</p>
            </div>
            <div className="saas-card">
              <ul className="divide-y divide-line">
                {ids.map((id) => (
                  <CheckRow key={id} id={id} open={openIds.has(id)} onToggle={toggle} />
                ))}
              </ul>
            </div>
          </section>
        );
      })}
    </div>
  );
}
