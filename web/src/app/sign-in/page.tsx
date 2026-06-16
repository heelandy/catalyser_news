import { KeyRound, Mail } from "lucide-react";

import { authConfiguration } from "@/auth";
import { requestMagicLink } from "@/app/sign-in/actions";
import { safeInternalRedirect } from "@/lib/authz";
import {
  createProtectedFormToken,
  PROTECTED_FORM_SCOPES,
  PROTECTED_FORM_TOKEN_FIELD,
} from "@/lib/protected-form";

export default async function SignInPage({
  searchParams,
}: {
  searchParams: Promise<{ callbackUrl?: string }>;
}) {
  const params = await searchParams;
  const callbackUrl = safeInternalRedirect(params.callbackUrl ?? null);
  const formToken = authConfiguration.emailAuthConfigured
    ? createProtectedFormToken({
        scope: PROTECTED_FORM_SCOPES.magicLink,
      })
    : null;

  return (
    <main className="access-shell">
      <section className="access-panel" aria-labelledby="sign-in-title">
        <div className="access-icon">
          <KeyRound size={24} />
        </div>
        <p className="eyebrow">Secure access</p>
        <h1 id="sign-in-title">Sign in by email</h1>
        <p>
          We will send a single-use sign-in link that expires after 15 minutes.
        </p>

        {authConfiguration.emailAuthConfigured ? (
          <form action={requestMagicLink} className="access-form">
            <input
              type="hidden"
              name={PROTECTED_FORM_TOKEN_FIELD}
              value={formToken ?? ""}
            />
            <label htmlFor="email">Email address</label>
            <div className="input-with-icon">
              <Mail size={18} aria-hidden="true" />
              <input
                id="email"
                name="email"
                type="email"
                autoComplete="email"
                required
              />
            </div>
            <input type="hidden" name="callbackUrl" value={callbackUrl} />
            <button type="submit">Send secure link</button>
          </form>
        ) : (
          <div className="configuration-notice" role="status">
            Email sign-in is ready but not enabled. Set RESEND_API_KEY and
            AUTH_EMAIL_FROM in web/.env.local, then restart the web server.
          </div>
        )}
      </section>
    </main>
  );
}
