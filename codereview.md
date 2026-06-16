# Code Review — Earnings calendar, source health, subscriber fields & channel integrations

**Date:** 2026-06-16
**Scope:** Working-tree diff vs `HEAD` plus new untracked files.
**Reviewer effort:** high (recall-biased).

Branches/areas under review:

- Python engine: `macro_earnings_calendar.py`, `macro_source_health.py`,
  `macro_subscriber_fields.py`, `catalyser_news.py`, `macro_news_feed.py`,
  `macro_pipeline_runner.py`, `macro_web_ingest.py`, `macro_daily_confirmation.py`.
- Web app: Telegram/Discord connection libs, admin integration settings,
  account preferences server actions + page, Prisma schema, env.

Findings are ranked most-severe first. Each has the concrete failure scenario
and the implementation needed to fix it.

---

## 1. Source-health files race between the news refresher and the unlocked fetch stages

**Where:** [macro_source_health.py:150-175](macro_source_health.py#L150-L175),
[macro_pipeline_runner.py:744-762](macro_pipeline_runner.py#L744-L762)

**Problem.** `record_attempts()` is a non-atomic read-modify-write: it reads the
whole `macro_source_health_history.jsonl`, appends, and rewrites the entire file,
then overwrites `macro_source_health.json` with a plain `write_text`. This diff
wires `record_attempts` into **three** writers that can run at the same time:

- the background `news_refresher_loop` thread runs `macro_news_feed.py` **under**
  `news_lock`;
- the main loop runs `live_calendar_fetch` (`catalyser_news.py`) and
  `earnings_calendar_fetch` (`macro_earnings_calendar.py`) **without** taking
  `news_lock` (only stages named `news_feed`/`live_regime_context` are guarded —
  see [macro_pipeline_runner.py:758-760](macro_pipeline_runner.py#L758-L760)).

Because the unguarded subprocesses never acquire `news_lock`, the lock gives **no**
mutual exclusion against them.

**Failure scenario.** The refresher fires while `live_calendar_fetch` is writing:
both read the same JSONL, both append their own attempts, and the last writer
wins — the other process's appended rows are silently lost. A dashboard reading
`macro_source_health.json` mid-write can also read a truncated/partial JSON and
throw.

**Implementation needed.**
- Make the write atomic and serialized in `macro_source_health.py`:
  - Write to a temp file in the same directory and `os.replace()` it into place
    for both the `.jsonl` and `.json` outputs (atomic on the same volume).
  - Guard the read-modify-write with a cross-process lock keyed on the history
    path — a lockfile via `msvcrt.locking` (Windows) / `fcntl.flock` (POSIX), or
    a small `portalocker`-style helper. At minimum, append-only writes to the
    JSONL (open with `"a"`) instead of rewrite, and only re-summarize from a
    consistent snapshot.
- Alternatively (simpler, lower-risk): in `macro_pipeline_runner.py`, run the
  source-health-writing stages under the same `news_lock` so the refresher and
  the fetch stages cannot write concurrently — i.e. include `live_calendar_fetch`
  and `earnings_calendar_fetch` in the locked set, or give each writer a distinct
  history file and merge for the summary.

---

## 2. Telegram webhook can only ever verify the 100 most-recently-updated pending connections

**Where:** [web/src/app/api/integrations/telegram/webhook/route.ts:49-67](web/src/app/api/integrations/telegram/webhook/route.ts#L49-L67)

**Problem.** The webhook loads candidate connections with
`orderBy: { updatedAt: "desc" }, take: 100` and then `.find()`s the HMAC match
in memory. If more than 100 unverified connections are pending (a plausible
state under load, or if stale pending rows accumulate because expired codes are
never cleaned up), a legitimate user whose row is not in the newest 100 will
never match — their valid code is silently dropped and the route returns
`{ ok: true, verified: false }`.

**Failure scenario.** 150 users start Telegram verification in a window. User #1
(now the oldest `updatedAt`) sends the correct code inside 15 minutes but is
beyond the `take: 100` slice → never verified, no error surfaced.

**Implementation needed.**
- Don't scan-and-match. Recompute the lookup deterministically: since the hash is
  `HMAC(secret, "${userId}:${code}")`, you cannot query by code without the
  userId. Two robust options:
  1. Store the code hash **without** the userId salt (e.g. `HMAC(secret, code)`)
     in an indexed column and look it up directly: `where: { verificationCodeHash,
     disabledAt: null, verifiedAt: null }`, then validate freshness. This removes
     the in-memory scan entirely.
  2. Keep the per-user salt but require the user to include a short account
     reference, or expand `take` and add a background sweep that disables expired
     pending rows so the active set stays small and bounded.
- Regardless, add a periodic cleanup that nulls `verificationCodeHash` / disables
  rows once `isTelegramVerificationFresh` is false, so the candidate set cannot
  grow unbounded.

---

## 3. `testIntegrationSettings` marks a provider `VERIFIED` without any live check

**Where:** [web/src/app/admin/integrations/actions.ts:95-114](web/src/app/admin/integrations/actions.ts#L95-L114),
[web/src/lib/integration-settings.ts:462-480](web/src/lib/integration-settings.ts#L462-L480)

**Problem.** `localIntegrationTest()` returns `IntegrationStatus.VERIFIED`
whenever the integration is enabled and no required keys are missing — it makes
**no** call to Resend/Telegram/Discord/Stripe. `testIntegrationSettings` then
writes `status: result.status` (= `VERIFIED`) back onto the `IntegrationSetting`
row and into the audit log.

**Failure scenario.** An admin pastes a wrong/expired API key, clicks "Test", and
the dashboard flips the provider to **VERIFIED** with a green state — even though
the credential would fail on first real use. The audit log records a false
"verified" event.

**Implementation needed.**
- Rename the status returned by a config-only check to something honest, e.g.
  `CONFIGURED` (not `VERIFIED`), and reserve `VERIFIED` for a status set only
  after a real provider round-trip succeeds.
- Either implement real per-provider test calls (Resend domains ping, Telegram
  `getMe`, Discord webhook test like `sendDiscordWebhookTest`, Stripe
  `balance.retrieve`) before setting `VERIFIED`, or change the test button copy
  and `localIntegrationTest` message to clearly say "local configuration check
  only" and stop persisting `VERIFIED`.

---

## 4. Admin integration secrets are stored but never consumed by the runtime

**Where:** [web/src/lib/integration-settings.ts:233-394](web/src/lib/integration-settings.ts#L233-L394),
[web/src/lib/telegram-connection.ts:13-24](web/src/lib/telegram-connection.ts#L13-L24),
[web/src/app/api/integrations/telegram/webhook/route.ts:16-22](web/src/app/api/integrations/telegram/webhook/route.ts#L16-L22)

**Problem.** `buildIntegrationSettingUpdate` encrypts and persists secrets
(`TELEGRAM_WEBHOOK_SECRET`, `TELEGRAM_BOT_TOKEN`, `RESEND_API_KEY`, Stripe keys,
etc.) into `IntegrationSetting.encryptedSecrets`. But every runtime consumer
reads from environment variables via `getServerEnv()` — the webhook route checks
`env.TELEGRAM_WEBHOOK_SECRET`, `telegramSecret()`/`discordSecret()` read
`AUTH_SECRET`/`ENGINE_INGEST_SECRET`. Nothing reads the DB-stored secrets back
out (there is `decryptIntegrationSecret`, but it has no callers in the diff).

**Failure scenario.** An operator configures Telegram entirely through the new
admin UI, sees it marked configured, but the webhook still returns
`503 telegram_webhook_not_configured` because `process.env.TELEGRAM_WEBHOOK_SECRET`
is empty. The UI implies the provider is set up when it is not.

> Note: `expectationAPP` lists the Super Admin integration settings UI as an
> unchecked `[ ]` item, so this is acknowledged WIP. It is called out because the
> persisted-but-unread secrets are a real operator trap and should be resolved
> before the UI is presented as functional.

**Implementation needed.**
- Make a single resolution path that prefers the managed `IntegrationSetting`
  (decrypted) and falls back to env — e.g. a `resolveProviderSecret(provider, key)`
  helper used by `getServerEnv` consumers — so saving in the UI actually takes
  effect; or
- Until that exists, mark the admin UI clearly as "writes are not yet live;
  configure via environment variables" and avoid showing a configured/verified
  state that the runtime does not honor.

---

## 5. `watchLevels` in the web payload can become a non-object

**Where:** [macro_web_ingest.py:752-759](macro_web_ingest.py#L752-L759),
[macro_web_ingest.py:820-827](macro_web_ingest.py#L820-L827)

**Problem.** `parse_json_field` returns the parsed JSON for **any** valid JSON
text and only falls back on `JSONDecodeError`. The canonical payload's
`watchLevels` is then whatever the field parsed to. The engine
(`macro_subscriber_fields.enrich_signal_row`) always emits a JSON **object**, but
`watch_levels_json` / `watchLevels` is also accepted from arbitrary upstream rows;
a value like `"[]"`, `"5"`, or `"true"` parses cleanly to a list/number/bool and
flows straight into `payload["signal"]["watchLevels"]` and
`payload["alert"]["watchLevels"]`.

**Failure scenario.** A row carries `watch_levels_json = "[]"`; `watchLevels`
becomes a list. If the web ingest schema (or the dashboard renderer) expects an
object/record, validation or rendering fails for that alert.

**Implementation needed.**
- Constrain `parse_json_field` (or the call site) to objects: if the parsed value
  is not a `dict`, return the fallback object. e.g.
  `parsed = json.loads(text); return parsed if isinstance(parsed, dict) else fallback`.

---

## Checked and considered OK

- `build_catalyst_rows` symbols handling: `symbols` is normalized to a list via
  `split_symbols(...)` at the top of the function, and `row_symbols` is a list in
  both branches, so the new per-event `symbols` override does not introduce a
  list/string inconsistency.
- `parse_engine_time` is defined in both `macro_subscriber_fields.py` and
  `macro_web_ingest.py`; no missing-import / `NameError`.
- Telegram/Discord HMAC + AES-GCM helpers use constant-time compare for the
  webhook secret and code hash, random IVs, and auth tags — crypto usage is sound.
- `parseDiscordWebhookUrl` enforces https + host allowlist + id/token shape; the
  duplicate-active-webhook check and `redirect()`-based control flow are correct
  (NEXT_REDIRECT propagates and is not swallowed by the surrounding try/catch).
- Combined macro write in `catalyser_news.py` only rewrites `--macro-output` when
  there are rows, so a total fetch failure leaves the prior file intact.

---

## Suggested fix order

1. **#1 source-health race** — data loss / corrupt JSON in the live pipeline.
2. **#2 Telegram `take: 100`** — silent verification failures for real users.
3. **#3 false `VERIFIED`** — misleading admin/operator state.
4. **#5 `watchLevels` shape** — cheap one-line guard, prevents bad payloads.
5. **#4 unread admin secrets** — finish or clearly gate the WIP admin UI.

---

# Rate limiting & public-API exposure review

## Existing baseline

The app already has a reusable, DB-backed rate limiter
([web/src/lib/auth-rate-limit.ts](web/src/lib/auth-rate-limit.ts) +
`evaluateAuthRateLimit` policy + `AuthRateLimit` model), but it is wired into
**only one** path: magic-link sign-in ([web/src/auth.ts:28](web/src/auth.ts#L28)).
None of the endpoints/actions added in this diff use it. The two pre-existing
webhooks (`/api/stripe/webhook`, `/api/engine/alerts`) also have no rate limit
and rely solely on signature/secret verification — so the new Telegram webhook is
**consistent** with the existing pattern, but the pattern itself leaves the
secret-gated surfaces unthrottled.

## A. Public / unauthenticated endpoint: Telegram webhook

**Where:** [web/src/app/api/integrations/telegram/webhook/route.ts](web/src/app/api/integrations/telegram/webhook/route.ts)

- **Public:** yes — `POST /api/integrations/telegram/webhook` is reachable by
  anyone. The only gate is the constant-time `x-telegram-bot-api-secret-token`
  header check, and an unset `TELEGRAM_WEBHOOK_SECRET` returns `503` (effectively
  closed until configured). An invalid secret returns `403` **before** any DB
  access, so unauthenticated callers cannot reach the query — good.
- **Rate limiting:** none. Risks:
  - **No body-size cap.** `await request.json()` reads the whole body; an App
    Router handler has no default size limit. A large body is parsed before any
    cheap rejection.
  - If the webhook secret ever leaks, every accepted request runs
    `findMany(take: 100)` + up to 100 HMAC computations (ties into finding #2) —
    an unauthenticated brute-force / DB-load amplifier with no throttle.

**Implementation needed.**
- Add a coarse per-IP (or per-secret) rate limit using the existing
  `AuthRateLimit`-style limiter before the DB query.
- Reject oversized bodies early (check `Content-Length` / read with a cap).
- These also mitigate finding #2's unbounded candidate scan.

## B. Authenticated server actions — no abuse throttle

**Where:** [web/src/app/account/preferences/actions.ts](web/src/app/account/preferences/actions.ts)

All are gated by `auth()` + `verifyProtectedFormToken` (CSRF), so they are **not
public**, but none are rate limited:

- `connectDiscordWebhook` — **the notable one.** Each submit triggers an
  **outbound** `POST` to a user-supplied Discord webhook
  ([discord-connection.ts:126-152](web/src/lib/discord-connection.ts#L126-L152)).
  - SSRF is mitigated: `parseDiscordWebhookUrl` enforces `https:` + a host
    allowlist (`discord.com` / `discordapp.com`) + id/token shape — so it is not
    a general SSRF.
  - But with no throttle, an authenticated user can use the server as an
    **unmetered relay** to spam verification messages to *any* valid Discord
    webhook (their own or a third party's), which can get the **server's IP
    rate-limited/blocked by Discord** and is a third-party spam vector.
  - **No timeout / AbortSignal** on the `fetch` to Discord → a slow or hanging
    Discord response holds the server action open with no upper bound. (Contrast
    the Python side, which passes `timeout=` to `requests`.)
- `startTelegramConnection` — unthrottled code generation; bounded to the user's
  own single row, so low risk, but a per-user cap is cheap insurance.

**Implementation needed.**
- Add a per-user rate limit (reuse the `AuthRateLimit` limiter keyed by
  `userId:action`) to `connectDiscordWebhook` and `startTelegramConnection`.
- Add an `AbortSignal.timeout(…)` to `sendDiscordWebhookTest`'s `fetch` and treat
  a timeout as a `DiscordConnectionError` (`test_failed`).

## C. Admin actions — low risk

`saveIntegrationSettings` / `testIntegrationSettings`
([web/src/app/admin/integrations/actions.ts](web/src/app/admin/integrations/actions.ts))
are gated by `requireAdmin()` + CSRF. Admin-only, so rate limiting is not urgent.

## D. Outbound public third-party APIs (engine side)

**Where:** [macro_earnings_calendar.py:202-206](macro_earnings_calendar.py#L202-L206)

- **Public API, no key:** `query1.finance.yahoo.com/v7/finance/calendar/earnings`
  is an unauthenticated public Yahoo endpoint. The diff calls it **per symbol in a
  sequential loop** ([macro_earnings_calendar.py:228-252](macro_earnings_calendar.py#L228-L252))
  with a request `timeout` but **no inter-request delay, no retry/backoff, and no
  handling of HTTP 429**.
- Graceful-degrade is OK: `raise_for_status()` → per-symbol exception → recorded
  as a failed attempt and an empty/partial CSV is still written, so the pipeline
  does not crash. But Yahoo's v7 calendar endpoint now commonly requires a
  crumb/cookie and returns `401`/`429` to bare requests, so this feed may simply
  fail in production with no backoff between 120-minute cycles.
- This matches the style of the pre-existing `macro_news_feed.py` /
  `catalyser_news.py` public-source fetches (also keyless, low-frequency), so it
  is consistent — just flagged for reliability.

**Implementation needed.**
- Add a small inter-symbol sleep and a bounded retry/backoff on `429`/`5xx`
  (respect `Retry-After`), and consider a crumb/cookie warm-up or a documented
  fallback provider so the earnings feed degrades predictably rather than always
  failing when Yahoo throttles.

## Summary

| Surface | Public? | Auth gate | Rate limited? | Action |
|---|---|---|---|---|
| `POST /api/integrations/telegram/webhook` | Yes | secret header (403 before DB) | **No** | Add per-IP limit + body cap |
| `connectDiscordWebhook` (action) | No | session + CSRF | **No** | Add per-user limit + fetch timeout |
| `startTelegramConnection` (action) | No | session + CSRF | **No** | Add per-user limit (low priority) |
| `saveIntegrationSettings` / `testIntegrationSettings` | No | admin + CSRF | No | OK (admin-only) |
| Yahoo earnings fetch (outbound) | Calls public keyless API | n/a | **No backoff** | Add retry/backoff + delay |
