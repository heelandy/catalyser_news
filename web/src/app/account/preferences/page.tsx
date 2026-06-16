import {
  BellRing,
  CheckCircle2,
  CircleSlash,
  MessageCircle,
  Send,
  Settings2,
  ShieldCheck,
} from "lucide-react";

import { saveAlertPreferences } from "@/app/account/preferences/actions";
import {
  EVENT_FAMILY_OPTIONS,
  SYMBOL_OPTIONS,
} from "@/lib/account-preferences";
import { formatDate, loadAccountSnapshot } from "@/lib/account-data";
import {
  createProtectedFormToken,
  PROTECTED_FORM_SCOPES,
  PROTECTED_FORM_TOKEN_FIELD,
} from "@/lib/protected-form";
import { requireUser } from "@/lib/server-auth";

export default async function PreferencesPage() {
  const user = await requireUser("/account/preferences");
  const snapshot = await loadAccountSnapshot(user);
  const formToken = createProtectedFormToken({
    scope: PROTECTED_FORM_SCOPES.accountPreferences,
    userId: user.id,
  });

  return (
    <main className="account-shell">
      <header className="account-header">
        <div>
          <p className="eyebrow">Subscriber dashboard</p>
          <h1>Alert preferences</h1>
          <span>
            {snapshot.plan.name} · {user.email}
          </span>
        </div>
        <a className="secondary-link" href="/account/billing">
          Billing
        </a>
      </header>

      <section className="account-grid">
        <form action={saveAlertPreferences} className="account-panel wide">
          <input
            type="hidden"
            name={PROTECTED_FORM_TOKEN_FIELD}
            value={formToken}
          />
          <div className="account-panel-heading">
            <div>
              <p className="eyebrow">Routing rules</p>
              <h2>Delivery preferences</h2>
            </div>
            <Settings2 size={20} />
          </div>

          <div className="preference-grid">
            <label className="toggle-row">
              <input
                type="checkbox"
                name="emailEnabled"
                defaultChecked={snapshot.preference.emailEnabled}
                disabled={!snapshot.channels.email.available}
              />
              <span>Email alerts</span>
              <small>
                {snapshot.channels.email.available
                  ? "Available for this plan"
                  : "Upgrade required"}
              </small>
            </label>
            <label className="toggle-row">
              <input
                type="checkbox"
                name="telegramEnabled"
                defaultChecked={snapshot.preference.telegramEnabled}
                disabled={!snapshot.channels.telegram.available}
              />
              <span>Telegram alerts</span>
              <small>
                {snapshot.channels.telegram.available
                  ? "Connection required"
                  : "Pro or Elite required"}
              </small>
            </label>
            <label className="toggle-row">
              <input
                type="checkbox"
                name="discordEnabled"
                defaultChecked={snapshot.preference.discordEnabled}
                disabled={!snapshot.channels.discord.available}
              />
              <span>Discord alerts</span>
              <small>
                {snapshot.channels.discord.available
                  ? "Connection required"
                  : "Pro or Elite required"}
              </small>
            </label>
          </div>

          <div className="form-grid">
            <label>
              <span>Minimum confidence</span>
              <input
                type="number"
                min="0"
                max="100"
                name="minimumConfidence"
                defaultValue={snapshot.preference.minimumConfidence}
              />
            </label>
            <label>
              <span>Minimum risk level</span>
              <select
                name="minimumRiskLevel"
                defaultValue={snapshot.preference.minimumRiskLevel}
              >
                {["LOW", "MEDIUM", "HIGH", "CRITICAL"].map((level) => (
                  <option key={level} value={level}>
                    {level}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>Quiet hours start</span>
              <input
                type="time"
                name="quietHoursStart"
                defaultValue={snapshot.preference.quietHours.start}
              />
            </label>
            <label>
              <span>Quiet hours end</span>
              <input
                type="time"
                name="quietHoursEnd"
                defaultValue={snapshot.preference.quietHours.end}
              />
            </label>
          </div>

          <label className="quiet-toggle">
            <input
              type="checkbox"
              name="quietHoursEnabled"
              defaultChecked={snapshot.preference.quietHours.enabled}
            />
            <span>Apply quiet hours</span>
          </label>

          <div className="choice-section">
            <strong>Event families</strong>
            <div className="choice-grid">
              {EVENT_FAMILY_OPTIONS.map((family) => (
                <label key={family}>
                  <input
                    type="checkbox"
                    name="eventFamilies"
                    value={family}
                    defaultChecked={snapshot.preference.eventFamilies.includes(
                      family,
                    )}
                  />
                  <span>{family.replaceAll("_", " ")}</span>
                </label>
              ))}
            </div>
          </div>

          <div className="choice-section">
            <strong>Symbols</strong>
            <div className="choice-grid compact">
              {SYMBOL_OPTIONS.map((symbol) => (
                <label key={symbol}>
                  <input
                    type="checkbox"
                    name="symbols"
                    value={symbol}
                    defaultChecked={snapshot.preference.symbols.includes(
                      symbol,
                    )}
                  />
                  <span>{symbol}</span>
                </label>
              ))}
            </div>
          </div>

          <button className="primary-submit" type="submit">
            Save preferences
          </button>
        </form>

        <article className="account-panel">
          <div className="account-panel-heading">
            <div>
              <p className="eyebrow">Channels</p>
              <h2>Verification</h2>
            </div>
            <ShieldCheck size={20} />
          </div>
          <div className="channel-list">
            <div className="channel-row">
              <BellRing size={17} />
              <div>
                <strong>Email</strong>
                <small>
                  {snapshot.channels.email.available
                    ? "Ready after email provider setup"
                    : "Not included in this plan"}
                </small>
              </div>
              {snapshot.channels.email.available ? (
                <CheckCircle2 size={17} />
              ) : (
                <CircleSlash size={17} />
              )}
            </div>
            <div className="channel-row">
              <Send size={17} />
              <div>
                <strong>Telegram</strong>
                <small>
                  {snapshot.channels.telegram.verified
                    ? "Verified"
                    : "Connection flow starts in Phase 8"}
                </small>
              </div>
              {snapshot.channels.telegram.verified ? (
                <CheckCircle2 size={17} />
              ) : (
                <CircleSlash size={17} />
              )}
            </div>
            <div className="channel-row">
              <MessageCircle size={17} />
              <div>
                <strong>Discord</strong>
                <small>
                  {snapshot.channels.discord.verified
                    ? "Verified"
                    : "Connection flow starts in Phase 8"}
                </small>
              </div>
              {snapshot.channels.discord.verified ? (
                <CheckCircle2 size={17} />
              ) : (
                <CircleSlash size={17} />
              )}
            </div>
          </div>
        </article>

        <article className="account-panel">
          <div className="account-panel-heading">
            <div>
              <p className="eyebrow">Delivery audit</p>
              <h2>Recent attempts</h2>
            </div>
            <BellRing size={20} />
          </div>
          <div className="compact-list">
            {snapshot.deliveryAttempts.length ? (
              snapshot.deliveryAttempts.map((attempt) => (
                <div className="compact-row" key={attempt.id}>
                  <div>
                    <strong>{attempt.alert.headline}</strong>
                    <small>
                      {attempt.channel} · {attempt.status} ·{" "}
                      {formatDate(attempt.createdAt)}
                    </small>
                  </div>
                </div>
              ))
            ) : (
              <p className="empty-state">No delivery attempts yet.</p>
            )}
          </div>
        </article>
      </section>

      <section className="disclaimer-band account-disclaimer">
        <ShieldCheck size={18} />
        <p>
          <strong>Educational and informational use only.</strong> Preferences
          control alert delivery and visibility, not trading outcomes. Alerts
          are not financial advice.
        </p>
      </section>
    </main>
  );
}
