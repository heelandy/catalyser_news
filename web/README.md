# Market Catalyst Web

Next.js/TypeScript application layer for the existing Python NQ Catalyst engine.

## Requirements

- Node.js 20.9 or newer
- npm
- PostgreSQL before Phase 2 database migrations

## Local Development

```powershell
cd .\web
Copy-Item .env.example .env.local
npm install
npm run dev
```

Open `http://localhost:3000`.

The Phase 1 dashboard reads the local Python engine status from the parent
folder on the server. No secrets or raw local files are exposed to browser code.

## Validation

```powershell
npm run lint
npm run typecheck
npm run test
npm run build
npm run db:validate
npm run db:generate
npm run db:seed
npm run check
npm run verify:account-dashboard
npm run verify:admin-dashboard
```

`GET /api/health` verifies the web process. `GET /api/ready` returns `503` until
`DATABASE_URL` is configured; this is expected until local PostgreSQL is set up.

## Database Workflow

From the repository root, install/configure the local PostgreSQL database:

```powershell
.\tools\setup_local_postgres.ps1
```

The script reuses a working configured database or creates an isolated
development cluster under ignored `web/.postgres-data` on port 5433. It writes
`DATABASE_URL` to ignored `web/.env.local`. Then run:

```powershell
npm run db:validate
npm run db:generate
npm run db:deploy
npm run db:seed
npm run db:verify
```

`npm run typecheck` validates project source. `npm run build` separately runs
Next.js route and generated-type validation.

The seed creates the Free, Basic, Pro, and Elite plan rows. It does not contain
secrets or subscriber data.

## Authentication

The web app uses Auth.js with PostgreSQL-backed sessions and passwordless Resend
magic links. Local sign-in is disabled until both values are present in ignored
`web/.env.local`:

```powershell
RESEND_API_KEY=re_...
AUTH_EMAIL_FROM="Market Catalyst <alerts@your-verified-domain.com>"
```

`tools/ensure_local_auth_secret.ps1` generates `AUTH_SECRET` for local use
without printing it to the terminal.

## Stripe Test Billing

Billing is implemented in fail-closed mode. The routes exist, but Checkout,
Customer Portal, and webhooks return configuration errors until Stripe test
credentials and test price IDs are configured.

Set these ignored local values first:

```powershell
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
```

Then sync the authoritative plan catalog into Stripe test products and prices:

```powershell
npm run stripe:sync-catalog
npm run db:verify
```

The sync script refuses live keys unless `-- --live` is passed. It creates Stripe
Products and monthly, quarterly, and annual recurring Prices for Basic, Pro, and
Elite, then writes the Stripe IDs into the existing `Plan` rows. Checkout reads
those database price IDs; it does not trust browser-submitted amounts.

Implemented billing endpoints:

- `POST /api/billing/checkout` creates a Stripe subscription Checkout Session.
- `POST /api/billing/portal` creates a Stripe Customer Portal Session for an
  existing Stripe customer.
- `POST /api/stripe/webhook` verifies the raw Stripe signature before handling
  subscription, invoice, payment-failure, refund, and dispute events.

Webhook event IDs are stored in `StripeWebhookEvent`, so replayed events are
ignored after the first processed copy. Card details are never stored locally;
the database stores only Stripe IDs, plan/subscription state, invoice metadata,
and payment status.

## Subscriber Dashboard

Authenticated account routes are protected by Auth.js:

- `/account/billing` shows resolved plan access, subscription state, billing
  period dates, Stripe Checkout buttons, Customer Portal entry, invoices,
  receipt links, and eligible alert history.
- `/account/preferences` saves alert delivery preferences into
  `AlertPreference` with server-side entitlement checks for email, Telegram,
  Discord, event families, symbols, confidence, risk level, and quiet hours.

Free users only see sent alerts after the configured plan delay and within the
plan's limited history window. Telegram and Discord connection setup is
available for plans that include those alert channels.

## Telegram Alerts

Telegram verification uses a short subscriber code and Telegram's webhook secret
header. Configure these ignored local values before live use:

```powershell
TELEGRAM_BOT_TOKEN=123456:bot-token
TELEGRAM_BOT_USERNAME=your_bot_username
TELEGRAM_WEBHOOK_SECRET=local-telegram-webhook-secret-0123456789abcdef
```

The subscriber dashboard generates a six-digit Telegram code and stores only an
HMAC hash of that code. The user sends the code to the configured bot within 15
minutes. Telegram posts updates to:

```text
POST /api/integrations/telegram/webhook
```

The route rejects requests unless the
`x-telegram-bot-api-secret-token` header matches `TELEGRAM_WEBHOOK_SECRET`.
After a valid code is received, the app stores the Telegram chat ID and marks the
connection verified. Disconnecting Telegram disables active connection rows.

Set the webhook with Telegram after the app has a public HTTPS URL:

```powershell
$botToken = "123456:bot-token"
$publicUrl = "https://your-domain.example.com/api/integrations/telegram/webhook"
$secret = "local-telegram-webhook-secret-0123456789abcdef"
Invoke-RestMethod -Method Post `
  -Uri "https://api.telegram.org/bot$botToken/setWebhook" `
  -Body @{ url = $publicUrl; secret_token = $secret }
```

## Discord Alerts

Discord verification is handled from `/account/preferences` for Pro and Elite
subscribers. The user pastes a Discord webhook URL, the server sends a
verification message to that webhook, and the connection is marked verified only
after Discord accepts the test. The webhook token is encrypted before it is
stored; the dashboard only displays a masked webhook ID.

Subscriber setup steps:

1. In Discord, create or select a channel.
2. Open channel settings, then Integrations, then Webhooks.
3. Create a webhook and copy its webhook URL.
4. Paste the URL into the Discord section of `/account/preferences`.
5. Confirm the Market Catalyst verification message appears in Discord.

Disconnecting Discord from the dashboard disables active webhook rows and clears
the encrypted token.

## Form and URL Protection

Server-rendered mutation forms include an encrypted, authenticated, time-limited
hidden token. The token is bound to a form scope and, for signed-in pages, the
current user ID. These forms reject missing, expired, tampered, wrong-scope, or
wrong-user tokens:

- Magic-link sign-in.
- Alert preference updates.
- Admin alert edit, approval, and rejection.

Callback and return URLs are restricted to safe internal paths. External,
protocol-relative, encoded-slash/backslash, `/api`, and `/_next` return targets
are rejected. The auth proxy protects `/admin/*` and all `/account/*` routes.
Cookie-authenticated billing API mutations also reject cross-origin `Origin`
headers.

This protects form integrity and CSRF-sensitive actions. Production deployments
must still run behind HTTPS so the full request body is encrypted in transit.

## Admin Dashboard

`/admin` is protected by the server-side `ADMIN` role check. It shows the
operations queue for incoming news events, generated market reactions, pending
alerts, alert/delivery history, subscribers, failed payments, and recent admin
audit activity.

Admins can edit pending alert copy, approve alerts, or reject alerts with a
required reason. Every admin mutation writes an `AdminAuditLog` row. Optional
auto-approval logic is present as a disabled-by-default policy gate and only
allows reviewed high-confidence event families when risk and regime-conflict
checks pass.

Approving an alert queues eligible per-subscriber delivery attempts. The queue
resolves the subscriber's active plan, checks alert preferences, enforces the
Basic daily limit, applies plan delay/priority timing, and stores the complete
subscriber payload in `AlertDeliveryAttempt`.

## Delivery Dispatch

Email fan-out is processed by a background command:

```powershell
npm run delivery:process -- --limit 25
```

The worker sends due email attempts through Resend, marks accepted messages as
`SENT`, records the Resend message ID when available, marks temporary failures
as `FAILED`, and moves attempts to `DEAD_LETTER` after the configured maximum
attempt count. The parent alert moves from `APPROVED` to `SENT` after the first
accepted email so subscriber history can show it. Retry timing uses exponential
backoff. One subscriber failure is recorded on that delivery attempt and does
not stop the rest of the batch.

Before live email delivery, configure ignored local values:

```powershell
RESEND_API_KEY=re_...
AUTH_EMAIL_FROM="Market Catalyst <alerts@your-verified-domain.com>"
```

Use dry-run mode to inspect due rows without sending email or requiring Resend
credentials:

```powershell
npm run delivery:process -- --dry-run --limit 5
```

Each delivered email includes headline, market bias, expected reaction,
confidence, risk level, short reasoning, risk warning, timestamp, expiry/time
sensitivity, watch levels, invalidation, and the educational disclaimer.
Telegram and Discord delivery remain pending until their connection flows are
implemented.

## Engine Ingestion

The Python engine can send canonical alert payloads to:

```text
POST /api/engine/alerts
```

The route requires:

- `ENGINE_INGEST_SECRET` in the web server environment, at least 32 characters.
- Header `x-market-catalyst-timestamp` with a Unix timestamp in seconds.
- Header `x-market-catalyst-signature` with
  `sha256=<hmac_sha256(secret, timestamp + "." + raw_body)>`.

Requests outside the five-minute replay window are rejected. Accepted payloads
are persisted transactionally as `NewsEvent`, `MarketReaction`, and `Alert`
records. Replayed or repeated payloads are made idempotent by
`idempotencyKey`/`sourceFingerprint` and return `duplicate: true`.

Local verification:

```powershell
$env:ENGINE_INGEST_SECRET="local-ingest-secret-0123456789abcdef0123456789abcdef"
npm run verify:engine-ingest
```

The Python sender lives at the repository root:

```powershell
python ..\macro_web_ingest.py --signals ..\macro_live_signal_current.csv --include-waiting --limit 1 --dry-run
```

Use `npm run db:migrate -- --name <migration_name>` only with a development
role that has permission to create Prisma's temporary shadow database. The
default app role intentionally uses `db:deploy` and does not receive that
permission.
