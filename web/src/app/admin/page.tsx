import {
  AlertTriangle,
  BadgeDollarSign,
  BellRing,
  CheckCircle2,
  ClipboardCheck,
  DatabaseZap,
  Newspaper,
  RadioTower,
  ShieldCheck,
  UserCog,
  Users,
  XCircle,
} from "lucide-react";

import { approveAlert, rejectAlert, saveAlertEdits } from "@/app/admin/actions";
import {
  loadAdminSnapshot,
  parseSubscriptionStateFilter,
} from "@/lib/admin-data";
import { evaluateAutoApprovalCandidate } from "@/lib/admin-workflow";
import { formatCurrency, formatDate } from "@/lib/account-data";
import {
  createProtectedFormToken,
  PROTECTED_FORM_SCOPES,
  PROTECTED_FORM_TOKEN_FIELD,
} from "@/lib/protected-form";
import { requireAdmin } from "@/lib/server-auth";

export const dynamic = "force-dynamic";

type AdminPageProps = {
  searchParams?: Promise<{ subscriptionState?: string }>;
};

function formatDateTime(value: Date | null) {
  if (!value) return "Not set";
  return new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(value);
}

function label(value: string) {
  return value.replaceAll("_", " ");
}

function autoApprovalReason(alert: {
  confidence: number;
  riskLevel: Parameters<typeof evaluateAutoApprovalCandidate>[0]["riskLevel"];
  marketReaction: {
    eventFamily: string;
    tradeState: string;
  } | null;
}) {
  const result = evaluateAutoApprovalCandidate({
    enabled: false,
    eventFamily: alert.marketReaction?.eventFamily ?? null,
    confidence: alert.confidence,
    riskLevel: alert.riskLevel,
    hasRegimeConflict:
      alert.marketReaction?.tradeState.includes("conflict") ?? false,
  });
  return result.reason;
}

export default async function AdminPage({ searchParams }: AdminPageProps) {
  const user = await requireAdmin();
  const params = await searchParams;
  const subscriptionState = parseSubscriptionStateFilter(
    params?.subscriptionState,
  );
  const snapshot = await loadAdminSnapshot({ subscriptionState });
  const reviewFormToken = createProtectedFormToken({
    scope: PROTECTED_FORM_SCOPES.adminAlertReview,
    userId: user.id,
  });

  return (
    <main className="account-shell admin-shell">
      <header className="account-header">
        <div>
          <p className="eyebrow">Administrator</p>
          <h1>Admin operations</h1>
          <span>Signed in as {user.email}</span>
        </div>
        <a className="secondary-link" href="/account/billing">
          Subscriber view
        </a>
      </header>

      <section className="account-metrics admin-metrics">
        <article>
          <span>Total users</span>
          <strong>{snapshot.metrics.totalUsers}</strong>
          <small>{snapshot.metrics.newUsers} new in the last 24 hours</small>
        </article>
        <article>
          <span>Pending approvals</span>
          <strong>{snapshot.metrics.pendingAlerts}</strong>
          <small>Draft and pending alerts awaiting review</small>
        </article>
        <article>
          <span>Failed payments</span>
          <strong>{snapshot.metrics.failedPayments}</strong>
          <small>{snapshot.metrics.failedDeliveries} failed deliveries</small>
        </article>
        <article>
          <span>Paid invoice revenue</span>
          <strong>{formatCurrency(snapshot.metrics.paidRevenueCents)}</strong>
          <small>Synced Stripe invoice totals</small>
        </article>
      </section>

      <section className="admin-status-strip" aria-label="Subscription status">
        {[
          ["ACTIVE", snapshot.metrics.subscriptions.active],
          ["TRIALING", snapshot.metrics.subscriptions.trialing],
          ["PAST_DUE", snapshot.metrics.subscriptions.pastDue],
          ["UNPAID", snapshot.metrics.subscriptions.unpaid],
          ["CANCELED", snapshot.metrics.subscriptions.canceled],
        ].map(([state, count]) => (
          <a
            className={
              snapshot.subscriptionState === state
                ? "status-filter active"
                : "status-filter"
            }
            href={`/admin?subscriptionState=${state}`}
            key={state}
          >
            <span>{label(String(state))}</span>
            <strong>{count}</strong>
          </a>
        ))}
        <a
          className={
            snapshot.subscriptionState === null
              ? "status-filter active"
              : "status-filter"
          }
          href="/admin"
        >
          <span>ALL</span>
          <strong>{snapshot.metrics.totalUsers}</strong>
        </a>
      </section>

      <section className="admin-grid">
        <article className="account-panel admin-panel wide">
          <div className="account-panel-heading">
            <div>
              <p className="eyebrow">Approval workflow</p>
              <h2>Review queue</h2>
            </div>
            <ClipboardCheck size={20} />
          </div>
          <div className="admin-review-list">
            {snapshot.reviewQueue.length ? (
              snapshot.reviewQueue.map((alert) => (
                <form className="admin-review-card" key={alert.id}>
                  <input
                    name={PROTECTED_FORM_TOKEN_FIELD}
                    type="hidden"
                    value={reviewFormToken}
                  />
                  <input name="alertId" type="hidden" value={alert.id} />
                  <div className="admin-review-meta">
                    <span>{label(alert.state)}</span>
                    <span>{alert.bias}</span>
                    <span>{alert.confidence}%</span>
                    <span>{alert.riskLevel}</span>
                  </div>
                  <label>
                    <span>Headline</span>
                    <input name="headline" defaultValue={alert.headline} />
                  </label>
                  <label>
                    <span>Summary</span>
                    <textarea name="summary" defaultValue={alert.summary} />
                  </label>
                  <div className="admin-edit-grid">
                    <label>
                      <span>Expected reaction</span>
                      <textarea
                        name="expectedReaction"
                        defaultValue={alert.expectedReaction}
                      />
                    </label>
                    <label>
                      <span>Risk warning</span>
                      <textarea
                        name="riskWarning"
                        defaultValue={alert.riskWarning}
                      />
                    </label>
                  </div>
                  <div className="admin-edit-grid">
                    <label>
                      <span>Invalidation</span>
                      <input
                        name="invalidation"
                        defaultValue={alert.invalidation ?? ""}
                      />
                    </label>
                    <label>
                      <span>Disclaimer</span>
                      <input
                        name="disclaimer"
                        defaultValue={alert.disclaimer}
                      />
                    </label>
                  </div>
                  <p className="panel-note">
                    Auto approval: {autoApprovalReason(alert)} Source:{" "}
                    {alert.marketReaction?.newsEvent?.source ?? "manual"} /{" "}
                    {alert.marketReaction?.eventFamily ?? "unmapped"}
                  </p>
                  <div className="admin-action-row">
                    <button formAction={saveAlertEdits} type="submit">
                      Save edits
                    </button>
                    <button
                      className="approve"
                      formAction={approveAlert}
                      type="submit"
                    >
                      Approve
                    </button>
                    <input
                      name="rejectionReason"
                      placeholder="Reason required for rejection"
                    />
                    <button
                      className="reject"
                      formAction={rejectAlert}
                      type="submit"
                    >
                      Reject
                    </button>
                  </div>
                </form>
              ))
            ) : (
              <p className="empty-state">No draft or pending alerts.</p>
            )}
          </div>
        </article>

        <article className="account-panel admin-panel">
          <div className="account-panel-heading">
            <div>
              <p className="eyebrow">Incoming source data</p>
              <h2>News events</h2>
            </div>
            <Newspaper size={20} />
          </div>
          <div className="compact-list">
            {snapshot.newsEvents.length ? (
              snapshot.newsEvents.map((event) => (
                <div className="compact-row" key={event.id}>
                  <div>
                    <strong>{event.headline}</strong>
                    <small>
                      {event.source} / {event.eventFamily ?? "unmapped"} /{" "}
                      {formatDateTime(event.occurredAt ?? event.fetchedAt)}
                    </small>
                  </div>
                </div>
              ))
            ) : (
              <p className="empty-state">No news events stored yet.</p>
            )}
          </div>
        </article>

        <article className="account-panel admin-panel">
          <div className="account-panel-heading">
            <div>
              <p className="eyebrow">Generated analysis</p>
              <h2>Market reactions</h2>
            </div>
            <RadioTower size={20} />
          </div>
          <div className="compact-list">
            {snapshot.marketReactions.length ? (
              snapshot.marketReactions.map((reaction) => (
                <div className="compact-row" key={reaction.id}>
                  <div>
                    <strong>
                      {reaction.symbol} {reaction.finalBias} /{" "}
                      {reaction.confidence}%
                    </strong>
                    <small>
                      {reaction.eventFamily} / release{" "}
                      {reaction.releaseRuleBias} / regime{" "}
                      {reaction.liveRegimeBias}
                    </small>
                  </div>
                </div>
              ))
            ) : (
              <p className="empty-state">No market reactions stored yet.</p>
            )}
          </div>
        </article>

        <article className="account-panel admin-panel">
          <div className="account-panel-heading">
            <div>
              <p className="eyebrow">Subscribers</p>
              <h2>Recent accounts</h2>
            </div>
            <Users size={20} />
          </div>
          <div className="admin-table" role="table">
            <div className="admin-table-row header" role="row">
              <span>User</span>
              <span>Role</span>
              <span>Plan</span>
              <span>Status</span>
              <span>Joined</span>
            </div>
            {snapshot.subscribers.length ? (
              snapshot.subscribers.map((subscriber) => {
                const subscription = subscriber.subscriptions[0];
                return (
                  <div className="admin-table-row" key={subscriber.id}>
                    <span>{subscriber.email}</span>
                    <span>{label(subscriber.role)}</span>
                    <span>{subscription?.plan.name ?? "Free"}</span>
                    <span>{subscription?.state ?? "NO_SUBSCRIPTION"}</span>
                    <span>{formatDate(subscriber.createdAt)}</span>
                  </div>
                );
              })
            ) : (
              <p className="empty-state">No subscribers match this filter.</p>
            )}
          </div>
        </article>

        <article className="account-panel admin-panel">
          <div className="account-panel-heading">
            <div>
              <p className="eyebrow">Payment issues</p>
              <h2>Failed payments</h2>
            </div>
            <BadgeDollarSign size={20} />
          </div>
          <div className="compact-list">
            {snapshot.failedPaymentRows.length ? (
              snapshot.failedPaymentRows.map((payment) => (
                <div className="compact-row" key={payment.id}>
                  <div>
                    <strong>{payment.user.email}</strong>
                    <small>
                      {formatCurrency(payment.amountCents, payment.currency)} /{" "}
                      {payment.failureCode ?? "failed"} /{" "}
                      {formatDateTime(payment.failedAt ?? payment.createdAt)}
                    </small>
                  </div>
                </div>
              ))
            ) : (
              <p className="empty-state">No failed payments are recorded.</p>
            )}
          </div>
        </article>

        <article className="account-panel admin-panel">
          <div className="account-panel-heading">
            <div>
              <p className="eyebrow">Delivery operations</p>
              <h2>Alert and delivery history</h2>
            </div>
            <BellRing size={20} />
          </div>
          <div className="compact-list">
            {snapshot.alertHistory.slice(0, 6).map((alert) => (
              <div className="compact-row" key={alert.id}>
                <div>
                  <strong>{alert.headline}</strong>
                  <small>
                    {label(alert.state)} / {alert.approvedBy?.email ?? ""}
                    {alert.rejectedBy?.email ?? ""} /{" "}
                    {formatDateTime(alert.updatedAt)}
                  </small>
                </div>
              </div>
            ))}
            {snapshot.deliveryHistory.slice(0, 6).map((attempt) => (
              <div className="compact-row" key={attempt.id}>
                <div>
                  <strong>{attempt.alert.headline}</strong>
                  <small>
                    {attempt.channel} / {attempt.status} / {attempt.user.email}
                  </small>
                </div>
              </div>
            ))}
            {!snapshot.alertHistory.length &&
              !snapshot.deliveryHistory.length && (
                <p className="empty-state">No alert history recorded yet.</p>
              )}
          </div>
        </article>

        <article className="account-panel admin-panel">
          <div className="account-panel-heading">
            <div>
              <p className="eyebrow">Audit trail</p>
              <h2>Recent admin actions</h2>
            </div>
            <ShieldCheck size={20} />
          </div>
          <div className="compact-list">
            {snapshot.auditLogs.length ? (
              snapshot.auditLogs.map((log) => (
                <div className="compact-row" key={log.id}>
                  <div>
                    <strong>{log.action}</strong>
                    <small>
                      {log.actorUser?.email ?? "system"} / {log.entityType} /{" "}
                      {formatDateTime(log.createdAt)}
                    </small>
                  </div>
                </div>
              ))
            ) : (
              <p className="empty-state">No admin actions recorded yet.</p>
            )}
          </div>
        </article>
      </section>

      <section className="admin-security-band">
        <ShieldCheck size={18} />
        <span>Admin page and actions require ADMIN role.</span>
        <CheckCircle2 size={18} />
        <span>Mutations are audited in AdminAuditLog.</span>
        <AlertTriangle size={18} />
        <span>Approve only alerts that are ready for subscriber fan-out.</span>
        <DatabaseZap size={18} />
        <span>External engine ingestion remains a separate Phase 7 task.</span>
        <UserCog size={18} />
        <span>Detailed staff roles and permissions are not enabled yet.</span>
        <XCircle size={18} />
        <span>
          Manual access overrides are intentionally not added in this pass.
        </span>
      </section>
    </main>
  );
}
