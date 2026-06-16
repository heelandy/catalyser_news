import {
  ArrowLeft,
  CheckCircle2,
  FlaskConical,
  KeyRound,
  Mail,
  MessageCircle,
  RadioTower,
  ReceiptText,
  Save,
  Send,
  ShieldCheck,
} from "lucide-react";

import {
  saveIntegrationSettings,
  testIntegrationSettings,
} from "@/app/admin/integrations/actions";
import {
  IntegrationProvider,
  IntegrationStatus,
} from "@/generated/prisma/enums";
import { getRequiredDatabase } from "@/lib/db";
import { loadIntegrationCards } from "@/lib/integration-settings";
import {
  createProtectedFormToken,
  PROTECTED_FORM_SCOPES,
  PROTECTED_FORM_TOKEN_FIELD,
} from "@/lib/protected-form";
import { requireAdmin } from "@/lib/server-auth";

export const dynamic = "force-dynamic";

function providerIcon(provider: IntegrationProvider) {
  if (provider === IntegrationProvider.RESEND_EMAIL) return <Mail size={19} />;
  if (provider === IntegrationProvider.TELEGRAM) return <Send size={19} />;
  if (provider === IntegrationProvider.DISCORD)
    return <MessageCircle size={19} />;
  if (provider === IntegrationProvider.STRIPE) return <ReceiptText size={19} />;
  return <RadioTower size={19} />;
}

function statusLabel(status: IntegrationStatus) {
  return status.replaceAll("_", " ");
}

function statusClass(status: IntegrationStatus) {
  if (status === IntegrationStatus.VERIFIED) return "good";
  if (status === IntegrationStatus.CONFIGURED) return "ready";
  if (
    status === IntegrationStatus.ERROR ||
    status === IntegrationStatus.NEEDS_ATTENTION
  )
    return "bad";
  return "quiet";
}

function formatDateTime(value: Date | null) {
  if (!value) return "Not tested";
  return new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(value);
}

export default async function AdminIntegrationsPage() {
  const user = await requireAdmin();
  const cards = await loadIntegrationCards(getRequiredDatabase());
  const formToken = createProtectedFormToken({
    scope: PROTECTED_FORM_SCOPES.adminIntegrationSettings,
    userId: user.id,
  });

  return (
    <main className="account-shell admin-shell">
      <header className="account-header">
        <div>
          <p className="eyebrow">Administrator</p>
          <h1>Integration settings</h1>
          <span>Signed in as {user.email}</span>
        </div>
        <a className="secondary-link" href="/admin">
          <ArrowLeft size={16} />
          Admin operations
        </a>
      </header>

      <section className="integration-summary">
        {cards.map((card) => (
          <article key={card.provider}>
            <span>{card.displayName}</span>
            <strong className={statusClass(card.status)}>
              {statusLabel(card.status)}
            </strong>
            <small>{card.source}</small>
          </article>
        ))}
      </section>

      <section className="integration-grid">
        {cards.map((card) => (
          <form className="integration-card" key={card.provider}>
            <input
              name={PROTECTED_FORM_TOKEN_FIELD}
              type="hidden"
              value={formToken}
            />
            <input name="provider" type="hidden" value={card.provider} />

            <div className="integration-card-heading">
              <div className="integration-icon">{providerIcon(card.provider)}</div>
              <div>
                <p className="eyebrow">{card.source}</p>
                <h2>{card.displayName}</h2>
                <span>{card.description}</span>
              </div>
              <strong className={`integration-status ${statusClass(card.status)}`}>
                {statusLabel(card.status)}
              </strong>
            </div>

            <label className="integration-toggle">
              <input
                defaultChecked={card.enabled}
                name="enabled"
                type="checkbox"
              />
              <span>Enabled</span>
            </label>

            <div className="integration-fields">
              {card.fields.map((field) => (
                <label key={field.key}>
                  <span>
                    {field.label}
                    {field.required ? <em>Required</em> : null}
                  </span>
                  {field.kind === "public" ? (
                    <input
                      defaultValue={card.publicValues[field.key] ?? ""}
                      name={`public:${field.key}`}
                      placeholder={field.placeholder}
                    />
                  ) : (
                    <div className="secret-input-row">
                      <input
                        autoComplete="off"
                        name={`secret:${field.key}`}
                        placeholder={
                          card.maskedSecrets[field.key]
                            ? `Current ${card.maskedSecrets[field.key]}`
                            : field.placeholder
                        }
                        type="password"
                      />
                      <KeyRound size={16} />
                    </div>
                  )}
                  <small>{field.help}</small>
                </label>
              ))}
            </div>

            {card.missingRequiredKeys.length ? (
              <p className="integration-warning">
                Missing: {card.missingRequiredKeys.join(", ")}
              </p>
            ) : (
              <p className="integration-ok">
                <CheckCircle2 size={15} />
                Required values are present.
              </p>
            )}

            <div className="integration-actions">
              <button formAction={saveIntegrationSettings} type="submit">
                <Save size={15} />
                Save
              </button>
              <button formAction={testIntegrationSettings} type="submit">
                <FlaskConical size={15} />
                Test
              </button>
            </div>

            <div className="integration-test-log">
              <strong>Last test</strong>
              <span>{card.lastTestMessage ?? "No saved test result."}</span>
              <small>{formatDateTime(card.lastTestedAt)}</small>
              {card.tests.map((test) => (
                <small key={test.id}>
                  {statusLabel(test.status)} / {formatDateTime(test.createdAt)}
                </small>
              ))}
            </div>
          </form>
        ))}
      </section>

      <section className="admin-security-band">
        <ShieldCheck size={18} />
        <span>Only ADMIN users can view or change integration settings.</span>
        <KeyRound size={18} />
        <span>Secret values are encrypted and never rendered after save.</span>
      </section>
    </main>
  );
}
