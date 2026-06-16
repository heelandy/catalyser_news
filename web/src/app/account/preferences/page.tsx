import {
  BellRing,
  CheckCircle2,
  CircleSlash,
  MessageCircle,
  Send,
  Settings2,
  ShieldCheck,
} from "lucide-react";

import {
  connectDiscordWebhook,
  disconnectDiscordWebhook,
  disconnectTelegramConnection,
  saveAlertPreferences,
  startTelegramConnection,
} from "@/app/account/preferences/actions";
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

export default async function PreferencesPage({
  searchParams,
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const user = await requireUser("/account/preferences");
  const snapshot = await loadAccountSnapshot(user);
  const params = searchParams ? await searchParams : {};
  const telegramCode =
    typeof params.telegramCode === "string" &&
    /^\d{6}$/.test(params.telegramCode)
      ? params.telegramCode
      : null;
  const discordStatus =
    typeof params.discordStatus === "string" ? params.discordStatus : null;
  const discordStatusMessage =
    discordStatus === "connected"
      ? "Discord webhook connected and verified."
      : discordStatus === "disconnected"
        ? "Discord webhook disconnected."
        : discordStatus === "invalid_url"
          ? "Enter a valid Discord webhook URL."
          : discordStatus === "test_failed"
            ? "Discord rejected the webhook test message."
            : discordStatus === "already_connected"
              ? "That Discord webhook is already connected to another account."
              : discordStatus === "missing_url"
                ? "Paste a Discord webhook URL before connecting."
                : discordStatus === "plan_required"
                  ? "Discord alerts require a Pro or Elite plan."
                  : null;
  const telegramBotLabel = snapshot.channels.telegram.botUsername
    ? `@${snapshot.channels.telegram.botUsername.replace(/^@/, "")}`
    : "your configured Telegram bot";
  const formToken = createProtectedFormToken({
    scope: PROTECTED_FORM_SCOPES.accountPreferences,
    userId: user.id,
  });
  const telegramConnectToken = createProtectedFormToken({
    scope: PROTECTED_FORM_SCOPES.accountTelegramConnect,
    userId: user.id,
  });
  const telegramDisconnectToken = createProtectedFormToken({
    scope: PROTECTED_FORM_SCOPES.accountTelegramDisconnect,
    userId: user.id,
  });
  const discordConnectToken = createProtectedFormToken({
    scope: PROTECTED_FORM_SCOPES.accountDiscordConnect,
    userId: user.id,
  });
  const discordDisconnectToken = createProtectedFormToken({
    scope: PROTECTED_FORM_SCOPES.accountDiscordDisconnect,
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
                    ? `Verified ${formatDate(snapshot.channels.telegram.verifiedAt)}`
                    : snapshot.channels.telegram.pending
                      ? "Verification pending"
                      : snapshot.channels.telegram.available
                        ? "Generate a verification code"
                        : "Pro or Elite required"}
                </small>
              </div>
              {snapshot.channels.telegram.verified ? (
                <CheckCircle2 size={17} />
              ) : (
                <CircleSlash size={17} />
              )}
            </div>
            {snapshot.channels.telegram.available ? (
              <div className="channel-action-block">
                {telegramCode ? (
                  <div className="verification-code">
                    <span>Telegram code</span>
                    <strong>{telegramCode}</strong>
                    <small>
                      Send this code to {telegramBotLabel} within 15 minutes.
                    </small>
                  </div>
                ) : null}
                {snapshot.channels.telegram.pending && !telegramCode ? (
                  <p className="panel-note">
                    A Telegram code is pending. Generate a new code if the last
                    one expired.
                  </p>
                ) : null}
                <div className="row-actions">
                  <form action={startTelegramConnection}>
                    <input
                      type="hidden"
                      name={PROTECTED_FORM_TOKEN_FIELD}
                      value={telegramConnectToken}
                    />
                    <button className="small-action-button" type="submit">
                      Generate code
                    </button>
                  </form>
                  {snapshot.channels.telegram.verified ||
                  snapshot.channels.telegram.pending ? (
                    <form action={disconnectTelegramConnection}>
                      <input
                        type="hidden"
                        name={PROTECTED_FORM_TOKEN_FIELD}
                        value={telegramDisconnectToken}
                      />
                      <button
                        className="small-action-button danger"
                        type="submit"
                      >
                        Disconnect
                      </button>
                    </form>
                  ) : null}
                </div>
              </div>
            ) : null}
            <div className="channel-row">
              <MessageCircle size={17} />
              <div>
                <strong>Discord</strong>
                <small>
                  {snapshot.channels.discord.verified
                    ? `Verified ${formatDate(snapshot.channels.discord.verifiedAt)}`
                    : snapshot.channels.discord.available
                      ? "Paste a Discord webhook URL"
                      : "Pro or Elite required"}
                </small>
              </div>
              {snapshot.channels.discord.verified ? (
                <CheckCircle2 size={17} />
              ) : (
                <CircleSlash size={17} />
              )}
            </div>
            {snapshot.channels.discord.available ? (
              <div className="channel-action-block">
                {discordStatusMessage ? (
                  <p
                    className={
                      discordStatus === "connected" ||
                      discordStatus === "disconnected"
                        ? "panel-note success"
                        : "panel-note danger"
                    }
                  >
                    {discordStatusMessage}
                  </p>
                ) : null}
                {snapshot.channels.discord.verified ? (
                  <p className="panel-note">
                    Active webhook {snapshot.channels.discord.webhookId}
                  </p>
                ) : null}
                <form action={connectDiscordWebhook} className="inline-form">
                  <input
                    type="hidden"
                    name={PROTECTED_FORM_TOKEN_FIELD}
                    value={discordConnectToken}
                  />
                  <input
                    aria-label="Discord webhook URL"
                    name="discordWebhookUrl"
                    placeholder="https://discord.com/api/webhooks/..."
                    type="url"
                    autoComplete="off"
                  />
                  <button className="small-action-button" type="submit">
                    Connect
                  </button>
                </form>
                {snapshot.channels.discord.verified ? (
                  <form action={disconnectDiscordWebhook}>
                    <input
                      type="hidden"
                      name={PROTECTED_FORM_TOKEN_FIELD}
                      value={discordDisconnectToken}
                    />
                    <button
                      className="small-action-button danger"
                      type="submit"
                    >
                      Disconnect
                    </button>
                  </form>
                ) : null}
              </div>
            ) : null}
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
