import Link from "next/link";

export default function ConsolePage() {
  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-fg">
            Security & Trust Console
          </h1>
          <p className="mt-1 text-xs sm:text-sm text-fg-muted">
            Real-time fraud telemetry, risk scores, and autonomous decision oversight.
          </p>
        </div>
      </div>

      {/* Metrics Grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { label: "Total Checkouts", value: "824", trend: "↑ 14% this month", trendColor: "text-emerald-400" },
          { label: "Avg Fraud Risk", value: "14 / 100", trend: "Safe threshold (<30)", trendColor: "text-fg-muted" },
          { label: "Neutralized Attacks", value: "38", trend: "Prompt injection & bot farms", trendColor: "text-blue-400" },
          { label: "Approval Holds", value: "12", trend: "Variant drift & price spikes", trendColor: "text-amber-400" },
        ].map((m) => (
          <div key={m.label} className="saas-card p-5">
            <span className="text-[11px] font-medium uppercase tracking-wider text-fg-muted">{m.label}</span>
            <div className="mt-2 text-2xl font-bold font-mono text-fg">{m.value}</div>
            <span className={`text-[11px] ${m.trendColor} mt-1.5 block font-medium`}>
              {m.trend}
            </span>
          </div>
        ))}
      </div>

      {/* Decision Breakdown & Integration Status */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="saas-card p-6 lg:col-span-2 space-y-4">
          <h2 className="text-sm font-semibold text-fg">
            Policy Decision Distribution
          </h2>
          <div className="space-y-3.5 text-xs">
            {[
              { label: "Clean Captures (Direct Settlement)", pct: "89.2%", width: "89.2%", color: "bg-emerald-500", textColor: "text-emerald-400" },
              { label: "Human Approval Holds (30-min window)", pct: "6.4%", width: "6.4%", color: "bg-amber-500", textColor: "text-amber-400" },
              { label: "Prompt Injection Voids", pct: "3.1%", width: "3.1%", color: "bg-rose-500", textColor: "text-rose-400" },
              { label: "Mandate & Access Rejections", pct: "1.3%", width: "1.3%", color: "bg-rose-700", textColor: "text-rose-400" },
            ].map((item) => (
              <div key={item.label} className="space-y-1.5">
                <div className="flex justify-between font-medium">
                  <span className="text-fg-2">{item.label}</span>
                  <span className={`font-mono font-semibold ${item.textColor}`}>{item.pct}</span>
                </div>
                <div className="h-2 w-full rounded-full bg-fg/6 overflow-hidden">
                  <div
                    className={`h-full rounded-full ${item.color}`}
                    style={{ width: item.width }}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Integration Status Card */}
        <div className="saas-card p-6 flex flex-col justify-between space-y-4">
          <div>
            <h2 className="text-sm font-semibold text-fg mb-3">
              Gateways & Services
            </h2>
            <div className="space-y-3 text-xs">
              <div className="flex items-center justify-between py-1 border-b border-fg/6">
                <span className="text-fg-2">PayPal Vault</span>
                <span className="saas-badge saas-badge-success text-[10px]">Connected</span>
              </div>
              <div className="flex items-center justify-between py-1 border-b border-fg/6">
                <span className="text-fg-2">Channel3 Feed</span>
                <span className="saas-badge saas-badge-success text-[10px]">Synced</span>
              </div>
              <div className="flex items-center justify-between py-1 border-b border-fg/6">
                <span className="text-fg-2">FastAPI Gateway</span>
                <span className="saas-badge saas-badge-success text-[10px]">Port 8000</span>
              </div>
              <div className="flex items-center justify-between py-1">
                <span className="text-fg-2">Vector Embeddings</span>
                <span className="saas-badge saas-badge-neutral text-[10px]">0.82 Cosine</span>
              </div>
            </div>
          </div>

          <div className="pt-3 border-t border-fg/8">
            <Link
              href="/wallet"
              className="intentlock-btn-outline w-full text-xs font-medium justify-center"
            >
              Configure Mandate Policies →
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
