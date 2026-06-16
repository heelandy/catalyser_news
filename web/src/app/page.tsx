import {
  Activity,
  BellRing,
  BookOpenCheck,
  CalendarClock,
  ChartNoAxesCombined,
  CheckCircle2,
  CircleDollarSign,
  Database,
  ExternalLink,
  Gauge,
  LockKeyhole,
  Newspaper,
  Radio,
  ServerCog,
  ShieldCheck,
  Users,
} from "lucide-react";

import { loadFoundationSnapshot } from "@/lib/foundation-snapshot";

export const dynamic = "force-dynamic";

const navigation = [
  { label: "Overview", icon: Gauge, active: true },
  { label: "Catalysts", icon: Newspaper },
  { label: "Alerts", icon: BellRing },
  { label: "Subscribers", icon: Users, locked: true },
  { label: "Billing", icon: CircleDollarSign, locked: true },
  { label: "Admin", icon: ShieldCheck, locked: true },
];

const engineCapabilities = [
  "Macro calendar polling",
  "Yahoo and TradingView news",
  "NQ reaction and regime model",
  "Email, Telegram, and Discord delivery",
];

function formatTimestamp(value: string | null) {
  if (!value) return "No completed cycle";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Invalid timestamp";
  return new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(date);
}

export default async function Home() {
  const snapshot = await loadFoundationSnapshot();
  const progress = snapshot.roadmap.total
    ? Math.round((snapshot.roadmap.completed / snapshot.roadmap.total) * 100)
    : 0;

  return (
    <div className="app-frame">
      <aside className="sidebar">
        <div className="brand-lockup">
          <div className="brand-mark" aria-hidden="true">
            <ChartNoAxesCombined size={22} strokeWidth={2.2} />
          </div>
          <div>
            <strong>Market Catalyst</strong>
            <span>Alert System</span>
          </div>
        </div>

        <nav className="primary-nav" aria-label="Primary navigation">
          {navigation.map(({ label, icon: Icon, active, locked }) => (
            <div
              className={`nav-item${active ? " active" : ""}${locked ? " locked" : ""}`}
              key={label}
              aria-current={active ? "page" : undefined}
            >
              <Icon size={18} />
              <span>{label}</span>
              {locked && (
                <LockKeyhole
                  className="nav-lock"
                  size={14}
                  aria-label="Planned"
                />
              )}
            </div>
          ))}
        </nav>

        <div className="sidebar-status">
          <span className="eyebrow">Build phase</span>
          <strong>Phase 4 Entitlements</strong>
          <div
            className="progress-track"
            aria-label={`${progress}% roadmap complete`}
          >
            <span style={{ width: `${progress}%` }} />
          </div>
          <small>
            {snapshot.roadmap.completed} of {snapshot.roadmap.total} checklist
            items complete
          </small>
        </div>
      </aside>

      <main className="main-surface">
        <header className="topbar">
          <div>
            <p className="eyebrow">Operations overview</p>
            <h1>Application Foundation</h1>
          </div>
          <div className="topbar-actions">
            <span className="environment-badge">Local development</span>
            <a
              className="icon-link"
              href="http://127.0.0.1:8787/dashboard/"
              title="Open legacy live dashboard"
            >
              <ExternalLink size={18} />
              <span>Live dashboard</span>
            </a>
          </div>
        </header>

        <section className="status-band" aria-label="Foundation status">
          <div className="status-copy">
            <span className={`status-dot ${snapshot.pipeline.tone}`} />
            <div>
              <strong>{snapshot.pipeline.label}</strong>
              <span>{snapshot.pipeline.detail}</span>
            </div>
          </div>
          <div className="status-time">
            <CalendarClock size={18} />
            <span>Last pipeline cycle</span>
            <strong>{formatTimestamp(snapshot.pipeline.finishedAt)}</strong>
          </div>
        </section>

        <section className="metric-grid" aria-label="System metrics">
          <article className="metric-tile">
            <div className="metric-icon green">
              <Activity size={20} />
            </div>
            <span>Pipeline cycle</span>
            <strong>{snapshot.pipeline.cycle ?? "--"}</strong>
            <small>
              {snapshot.pipeline.ok
                ? "Last run completed"
                : "Awaiting healthy run"}
            </small>
          </article>
          <article className="metric-tile">
            <div className="metric-icon amber">
              <BellRing size={20} />
            </div>
            <span>Latest alerts</span>
            <strong>{snapshot.alerts.latestCount}</strong>
            <small>
              {snapshot.alerts.totalSignals} signals in latest snapshot
            </small>
          </article>
          <article className="metric-tile">
            <div className="metric-icon cyan">
              <Database size={20} />
            </div>
            <span>PostgreSQL</span>
            <strong>
              {snapshot.database.configured ? "Configured" : "Pending"}
            </strong>
            <small>
              {snapshot.database.configured
                ? "Connection URL detected"
                : "Set DATABASE_URL for Phase 2"}
            </small>
          </article>
          <article className="metric-tile">
            <div className="metric-icon red">
              <ShieldCheck size={20} />
            </div>
            <span>Security gate</span>
            <strong>Required</strong>
            <small>High-risk findings must be fixed before launch</small>
          </article>
        </section>

        <section className="content-grid">
          <article className="work-panel engine-panel">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">Existing Python engine</p>
                <h2>Operational capabilities</h2>
              </div>
              <Radio size={20} />
            </div>
            <div className="capability-list">
              {engineCapabilities.map((capability) => (
                <div className="capability-row" key={capability}>
                  <CheckCircle2 size={17} />
                  <span>{capability}</span>
                </div>
              ))}
            </div>
            <div
              className="signal-visual"
              aria-label="Pipeline activity visual"
            >
              {[34, 62, 48, 78, 54, 88, 70, 96, 66, 82, 58, 90].map(
                (height, index) => (
                  <span key={index} style={{ height: `${height}%` }} />
                ),
              )}
            </div>
          </article>

          <article className="work-panel roadmap-panel">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">Commercial application</p>
                <h2>Foundation gates</h2>
              </div>
              <BookOpenCheck size={20} />
            </div>
            <div className="gate-list">
              <div className="gate-row complete">
                <CheckCircle2 size={18} />
                <div>
                  <strong>Next.js application</strong>
                  <span>App Router and TypeScript</span>
                </div>
              </div>
              <div className="gate-row complete">
                <CheckCircle2 size={18} />
                <div>
                  <strong>Environment boundary</strong>
                  <span>Server-side Zod validation</span>
                </div>
              </div>
              <div className="gate-row complete">
                <CheckCircle2 size={18} />
                <div>
                  <strong>Database migration</strong>
                  <span>PostgreSQL schema and plans verified</span>
                </div>
              </div>
              <div className="gate-row complete">
                <Users size={18} />
                <div>
                  <strong>Authentication foundation</strong>
                  <span>Auth.js sessions and route guards active</span>
                </div>
              </div>
              <div className="gate-row complete">
                <CheckCircle2 size={18} />
                <div>
                  <strong>Plan entitlements</strong>
                  <span>Catalog, database seed, and access tests verified</span>
                </div>
              </div>
              <div className="gate-row pending">
                <ServerCog size={18} />
                <div>
                  <strong>Stripe test mode</strong>
                  <span>Products, prices, Checkout, and webhooks pending</span>
                </div>
              </div>
            </div>
          </article>
        </section>

        <section className="disclaimer-band">
          <ShieldCheck size={18} />
          <p>
            <strong>Educational and informational use only.</strong> Market
            analysis is probabilistic and is not financial advice or a guarantee
            of trading outcomes.
          </p>
        </section>
      </main>
    </div>
  );
}
