import {
  AlertTriangle,
  CalendarClock,
  Download,
  FileText,
  History,
  ShieldCheck,
} from "lucide-react";

import { BillingActionButton } from "@/app/account/billing/billing-actions";
import { BillingInterval } from "@/generated/prisma/enums";
import {
  formatCurrency,
  formatDate,
  loadAccountSnapshot,
  periodLabel,
} from "@/lib/account-data";
import { PLAN_CATALOG } from "@/lib/plan-catalog";
import { requireUser } from "@/lib/server-auth";

const paidPlanCodes = ["basic", "pro", "elite"] as const;

export default async function BillingPage() {
  const user = await requireUser("/account/billing");
  const snapshot = await loadAccountSnapshot(user);
  const periodDate =
    snapshot.currentSubscription?.trialEndsAt ??
    snapshot.currentSubscription?.graceEndsAt ??
    snapshot.currentSubscription?.currentPeriodEnd ??
    null;

  return (
    <main className="account-shell">
      <header className="account-header">
        <div>
          <p className="eyebrow">Subscriber dashboard</p>
          <h1>Billing and access</h1>
          <span>{user.email}</span>
        </div>
        <BillingActionButton mode="portal" label="Manage in Stripe" />
      </header>

      {!snapshot.billingConfigured && (
        <section className="account-warning">
          <AlertTriangle size={18} />
          <span>
            Stripe test keys are not configured. Billing buttons are visible but
            will not open live Stripe flows until local test credentials and
            price IDs are added.
          </span>
        </section>
      )}

      <section className="account-metrics" aria-label="Billing summary">
        <article>
          <span>Current plan</span>
          <strong>{snapshot.plan.name}</strong>
          <small>{snapshot.plan.description}</small>
        </article>
        <article>
          <span>Subscription state</span>
          <strong>{snapshot.status.replaceAll("_", " ")}</strong>
          <small>
            {snapshot.currentSubscription?.cancelAtPeriodEnd
              ? "Cancellation scheduled"
              : "Access is resolved server-side"}
          </small>
        </article>
        <article>
          <span>{periodLabel(snapshot.currentSubscription)}</span>
          <strong>{formatDate(periodDate)}</strong>
          <small>
            {snapshot.entitlements.alertHistoryDays === null
              ? "Full alert history"
              : `${snapshot.entitlements.alertHistoryDays} day alert history`}
          </small>
        </article>
      </section>

      <section className="account-grid">
        <article className="account-panel wide">
          <div className="account-panel-heading">
            <div>
              <p className="eyebrow">Plan options</p>
              <h2>Upgrade or change billing interval</h2>
            </div>
            <ShieldCheck size={20} />
          </div>
          <div className="plan-table">
            {paidPlanCodes.map((code) => {
              const plan = PLAN_CATALOG[code];
              const current = snapshot.plan.code === code;
              return (
                <div className="plan-row" key={code}>
                  <div>
                    <strong>
                      {plan.name}
                      {current && <span>Current</span>}
                    </strong>
                    <small>{plan.description}</small>
                  </div>
                  <div className="plan-prices">
                    <BillingActionButton
                      mode="checkout"
                      planCode={code}
                      interval={BillingInterval.MONTHLY}
                      label={`${formatCurrency(plan.prices.MONTHLY)}/mo`}
                    />
                    <BillingActionButton
                      mode="checkout"
                      planCode={code}
                      interval={BillingInterval.QUARTERLY}
                      label={`${formatCurrency(plan.prices.QUARTERLY)}/qtr`}
                    />
                    <BillingActionButton
                      mode="checkout"
                      planCode={code}
                      interval={BillingInterval.ANNUAL}
                      label={`${formatCurrency(plan.prices.ANNUAL)}/yr`}
                    />
                  </div>
                </div>
              );
            })}
          </div>
          <p className="panel-note">
            Existing subscriptions, cancellations, resumes, payment-method
            changes, and invoices are handled through Stripe Customer Portal
            after a Stripe customer exists.
          </p>
        </article>

        <article className="account-panel">
          <div className="account-panel-heading">
            <div>
              <p className="eyebrow">Invoices</p>
              <h2>History and receipts</h2>
            </div>
            <FileText size={20} />
          </div>
          <div className="compact-list">
            {snapshot.invoices.length ? (
              snapshot.invoices.map((invoice) => (
                <div className="compact-row" key={invoice.id}>
                  <div>
                    <strong>{invoice.number ?? invoice.status}</strong>
                    <small>
                      {formatDate(invoice.createdAt)} ·{" "}
                      {formatCurrency(invoice.totalCents, invoice.currency)}
                    </small>
                  </div>
                  <div className="row-actions">
                    {invoice.hostedUrl && <a href={invoice.hostedUrl}>View</a>}
                    {invoice.pdfUrl && (
                      <a href={invoice.pdfUrl} aria-label="Download receipt">
                        <Download size={15} />
                      </a>
                    )}
                  </div>
                </div>
              ))
            ) : (
              <p className="empty-state">No invoices have been synced yet.</p>
            )}
          </div>
        </article>

        <article className="account-panel">
          <div className="account-panel-heading">
            <div>
              <p className="eyebrow">Eligible alerts</p>
              <h2>Catalyst history</h2>
            </div>
            <History size={20} />
          </div>
          <div className="compact-list">
            {snapshot.visibleAlerts.length ? (
              snapshot.visibleAlerts.map((alert) => (
                <div className="compact-row" key={alert.id}>
                  <div>
                    <strong>{alert.headline}</strong>
                    <small>
                      {alert.bias} · {alert.confidence}% ·{" "}
                      {formatDate(alert.sentAt ?? alert.createdAt)}
                    </small>
                  </div>
                </div>
              ))
            ) : (
              <p className="empty-state">
                No eligible sent alerts are visible for this plan yet.
              </p>
            )}
          </div>
        </article>
      </section>

      <section className="disclaimer-band account-disclaimer">
        <CalendarClock size={18} />
        <p>
          <strong>Educational and informational use only.</strong> Billing
          status controls access to alert summaries, but market analysis remains
          probabilistic and is not financial advice.
        </p>
      </section>
    </main>
  );
}
