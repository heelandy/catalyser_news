import {
  AlertChannel,
  AlertState,
  DeliveryStatus,
} from "@/generated/prisma/enums";
import type { Prisma } from "@/generated/prisma/client";
import { retryDelaySeconds, type DeliveryPayload } from "@/lib/delivery-policy";

export const DEFAULT_MAX_DELIVERY_ATTEMPTS = 5;

export type DeliveryFailureCategory =
  | "configuration"
  | "invalid_recipient"
  | "network"
  | "provider"
  | "rate_limited"
  | "unexpected";

export type EmailMessage = {
  to: string;
  subject: string;
  text: string;
  html: string;
  idempotencyKey: string;
};

export type EmailSendResult = {
  providerMessageId?: string;
};

export type EmailSender = (message: EmailMessage) => Promise<EmailSendResult>;

type AlertSnapshot = {
  id: string;
  headline: string;
  summary: string;
  bias: string;
  expectedReaction: string;
  confidence: number;
  riskLevel: string;
  reasoning: string;
  riskWarning: string;
  watchLevels: Prisma.JsonValue | null;
  invalidation: string | null;
  disclaimer: string;
  createdAt: Date;
  expiresAt: Date | null;
};

export type DeliveryAttemptWithContext = {
  id: string;
  channel: string;
  status: string;
  idempotencyKey: string | null;
  attemptNumber: number;
  rawPayload: Prisma.JsonValue | null;
  alert: AlertSnapshot;
  user: {
    id: string;
    email: string;
    deletedAt: Date | null;
  };
};

export type DeliveryDispatchDatabase = {
  alert: {
    updateMany(args: Prisma.AlertUpdateManyArgs): Promise<unknown>;
  };
  alertDeliveryAttempt: {
    findMany(
      args: Prisma.AlertDeliveryAttemptFindManyArgs,
    ): Promise<DeliveryAttemptWithContext[]>;
    update(args: {
      where: Prisma.AlertDeliveryAttemptWhereUniqueInput;
      data: Prisma.AlertDeliveryAttemptUpdateInput;
    }): Promise<unknown>;
  };
};

export type DeliveryAttemptResult = {
  attemptId: string;
  status: "sent" | "failed" | "dead_letter" | "skipped" | "error";
  failureCategory?: DeliveryFailureCategory;
  failureMessage?: string;
};

export type DeliveryDispatchSummary = {
  checked: number;
  sent: number;
  failed: number;
  deadLettered: number;
  skipped: number;
  errors: DeliveryAttemptResult[];
};

export class DeliveryDispatchError extends Error {
  readonly category: DeliveryFailureCategory;

  constructor(category: DeliveryFailureCategory, message: string) {
    super(message);
    this.name = "DeliveryDispatchError";
    this.category = category;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function stringValue(
  value: Record<string, unknown>,
  key: keyof DeliveryPayload,
  fallback: string,
) {
  const candidate = value[key];
  return typeof candidate === "string" && candidate.trim()
    ? candidate
    : fallback;
}

function nullableStringValue(
  value: Record<string, unknown>,
  key: keyof DeliveryPayload,
  fallback: string | null,
) {
  const candidate = value[key];
  return typeof candidate === "string" && candidate.trim()
    ? candidate
    : fallback;
}

function numberValue(
  value: Record<string, unknown>,
  key: keyof DeliveryPayload,
  fallback: number,
) {
  const candidate = value[key];
  return typeof candidate === "number" && Number.isFinite(candidate)
    ? candidate
    : fallback;
}

function payloadFromAlert(alert: AlertSnapshot): DeliveryPayload {
  return {
    alertId: alert.id,
    headline: alert.headline,
    summary: alert.summary,
    marketBias: alert.bias as DeliveryPayload["marketBias"],
    expectedReaction: alert.expectedReaction,
    confidence: alert.confidence,
    riskLevel: alert.riskLevel as DeliveryPayload["riskLevel"],
    shortReasoning: alert.reasoning,
    riskWarning: alert.riskWarning,
    timestamp: alert.createdAt.toISOString(),
    expiresAt: alert.expiresAt?.toISOString() ?? null,
    timeSensitivity: alert.expiresAt
      ? `Expires ${alert.expiresAt.toISOString()}`
      : "No explicit expiry set",
    watchLevels: alert.watchLevels,
    invalidation: alert.invalidation,
    disclaimer: alert.disclaimer,
  };
}

export function deliveryPayloadForAttempt(
  attempt: DeliveryAttemptWithContext,
): DeliveryPayload {
  const fallback = payloadFromAlert(attempt.alert);
  if (!isRecord(attempt.rawPayload)) return fallback;

  return {
    alertId: stringValue(attempt.rawPayload, "alertId", fallback.alertId),
    headline: stringValue(attempt.rawPayload, "headline", fallback.headline),
    summary: stringValue(attempt.rawPayload, "summary", fallback.summary),
    marketBias: stringValue(
      attempt.rawPayload,
      "marketBias",
      fallback.marketBias,
    ) as DeliveryPayload["marketBias"],
    expectedReaction: stringValue(
      attempt.rawPayload,
      "expectedReaction",
      fallback.expectedReaction,
    ),
    confidence: numberValue(
      attempt.rawPayload,
      "confidence",
      fallback.confidence,
    ),
    riskLevel: stringValue(
      attempt.rawPayload,
      "riskLevel",
      fallback.riskLevel,
    ) as DeliveryPayload["riskLevel"],
    shortReasoning: stringValue(
      attempt.rawPayload,
      "shortReasoning",
      fallback.shortReasoning,
    ),
    riskWarning: stringValue(
      attempt.rawPayload,
      "riskWarning",
      fallback.riskWarning,
    ),
    timestamp: stringValue(attempt.rawPayload, "timestamp", fallback.timestamp),
    expiresAt: nullableStringValue(
      attempt.rawPayload,
      "expiresAt",
      fallback.expiresAt,
    ),
    timeSensitivity: stringValue(
      attempt.rawPayload,
      "timeSensitivity",
      fallback.timeSensitivity,
    ),
    watchLevels: Object.hasOwn(attempt.rawPayload, "watchLevels")
      ? attempt.rawPayload.watchLevels
      : fallback.watchLevels,
    invalidation: nullableStringValue(
      attempt.rawPayload,
      "invalidation",
      fallback.invalidation,
    ),
    disclaimer: stringValue(
      attempt.rawPayload,
      "disclaimer",
      fallback.disclaimer,
    ),
  };
}

function escapeHtml(value: string) {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function compactSubject(value: string) {
  const subject = `[Market Catalyst] ${value.replace(/\s+/g, " ").trim()}`;
  return subject.length > 140 ? `${subject.slice(0, 137)}...` : subject;
}

function formatWatchLevels(value: unknown) {
  if (Array.isArray(value)) {
    const items = value.filter(
      (item): item is string | number =>
        typeof item === "string" || typeof item === "number",
    );
    return items.length ? items.join(", ") : "Not provided";
  }

  if (isRecord(value)) {
    const entries = Object.entries(value)
      .map(([key, entry]) => {
        if (Array.isArray(entry)) {
          return `${key}: ${entry.join(", ")}`;
        }
        return `${key}: ${String(entry)}`;
      })
      .filter((line) => line.trim().length > 0);
    return entries.length ? entries.join("; ") : "Not provided";
  }

  return "Not provided";
}

export function renderDeliveryEmail(payload: DeliveryPayload) {
  const fields = [
    ["Headline", payload.headline],
    ["Summary", payload.summary],
    ["Market bias", payload.marketBias],
    ["Expected reaction", payload.expectedReaction],
    ["Confidence", `${payload.confidence}%`],
    ["Risk level", payload.riskLevel],
    ["Short reasoning", payload.shortReasoning],
    ["Risk warning", payload.riskWarning],
    ["Timestamp", payload.timestamp],
    [
      "Expiry / time sensitivity",
      payload.timeSensitivity ||
        (payload.expiresAt ? `Expires ${payload.expiresAt}` : "Not provided"),
    ],
    ["Watch levels", formatWatchLevels(payload.watchLevels)],
    ["Invalidation", payload.invalidation ?? "Not provided"],
    ["Disclaimer", payload.disclaimer],
  ];

  const text = fields
    .map(([label, value]) => `${label}: ${value}`)
    .join("\n\n");

  const htmlRows = fields
    .map(
      ([label, value]) => `<tr>
  <th align="left" style="padding:10px 12px;border-bottom:1px solid #d9e2df;color:#56615e;font-size:12px;text-transform:uppercase;letter-spacing:.04em;">${escapeHtml(label)}</th>
  <td style="padding:10px 12px;border-bottom:1px solid #d9e2df;color:#111816;">${escapeHtml(value)}</td>
</tr>`,
    )
    .join("\n");

  return {
    subject: compactSubject(payload.headline),
    text,
    html: `<div style="font-family:Arial,sans-serif;line-height:1.45;color:#111816;">
  <h1 style="font-size:22px;margin:0 0 16px;">${escapeHtml(payload.headline)}</h1>
  <table cellpadding="0" cellspacing="0" width="100%" style="border-collapse:collapse;border:1px solid #d9e2df;border-radius:6px;overflow:hidden;">
${htmlRows}
  </table>
</div>`,
  };
}

export function sanitizeFailureMessage(error: unknown, maxLength = 600) {
  const raw =
    error instanceof Error
      ? error.message
      : typeof error === "string"
        ? error
        : "Unknown delivery failure.";
  const redacted = raw
    .replace(/Bearer\s+[A-Za-z0-9._~+/-]+=*/gi, "Bearer [redacted]")
    .replace(/re_[A-Za-z0-9_:-]+/g, "re_[redacted]")
    .replace(/whsec_[A-Za-z0-9_:-]+/g, "whsec_[redacted]")
    .trim();
  return redacted.length > maxLength
    ? `${redacted.slice(0, maxLength - 3)}...`
    : redacted;
}

export function classifyDeliveryError(error: unknown): DeliveryFailureCategory {
  if (error instanceof DeliveryDispatchError) return error.category;
  if (error instanceof TypeError) return "network";
  return "unexpected";
}

export function buildDeliveryFailureUpdate({
  attemptNumber,
  error,
  maxAttempts = DEFAULT_MAX_DELIVERY_ATTEMPTS,
  now = new Date(),
}: {
  attemptNumber: number;
  error: unknown;
  maxAttempts?: number;
  now?: Date;
}): Prisma.AlertDeliveryAttemptUpdateInput {
  const nextAttemptNumber = attemptNumber + 1;
  const isDeadLetter = nextAttemptNumber >= maxAttempts;
  const failureCategory = classifyDeliveryError(error);
  const nextRetryAt = isDeadLetter
    ? null
    : new Date(now.getTime() + retryDelaySeconds(nextAttemptNumber) * 1000);

  return {
    status: isDeadLetter ? DeliveryStatus.DEAD_LETTER : DeliveryStatus.FAILED,
    attemptNumber: nextAttemptNumber,
    nextRetryAt,
    failedAt: now,
    failureCategory,
    failureMessage: sanitizeFailureMessage(error),
  };
}

export function createResendEmailSender({
  apiKey,
  from,
  endpoint = "https://api.resend.com/emails",
  fetchFn = fetch,
}: {
  apiKey?: string;
  from?: string;
  endpoint?: string;
  fetchFn?: typeof fetch;
}): EmailSender {
  return async (message) => {
    const trimmedApiKey = apiKey?.trim();
    const trimmedFrom = from?.trim();
    if (!trimmedApiKey) {
      throw new DeliveryDispatchError(
        "configuration",
        "RESEND_API_KEY is required before email delivery can run.",
      );
    }
    if (!trimmedFrom) {
      throw new DeliveryDispatchError(
        "configuration",
        "AUTH_EMAIL_FROM is required before email delivery can run.",
      );
    }

    const response = await fetchFn(endpoint, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${trimmedApiKey}`,
        "Content-Type": "application/json",
        "Idempotency-Key": message.idempotencyKey,
      },
      body: JSON.stringify({
        from: trimmedFrom,
        to: message.to,
        subject: message.subject,
        text: message.text,
        html: message.html,
      }),
    });

    const body = await response.text();
    let parsed: unknown = null;
    try {
      parsed = body ? JSON.parse(body) : null;
    } catch {
      parsed = null;
    }

    if (!response.ok) {
      const category =
        response.status === 429
          ? "rate_limited"
          : response.status === 401 || response.status === 403
            ? "configuration"
            : "provider";
      throw new DeliveryDispatchError(
        category,
        `Resend rejected email with HTTP ${response.status}: ${body.slice(0, 300)}`,
      );
    }

    return {
      providerMessageId:
        isRecord(parsed) && typeof parsed.id === "string"
          ? parsed.id
          : undefined,
    };
  };
}

export async function listDueEmailDeliveryAttempts(
  database: DeliveryDispatchDatabase,
  {
    limit = 25,
    now = new Date(),
  }: {
    limit?: number;
    now?: Date;
  } = {},
) {
  return database.alertDeliveryAttempt.findMany({
    where: {
      channel: AlertChannel.EMAIL,
      status: { in: [DeliveryStatus.QUEUED, DeliveryStatus.FAILED] },
      OR: [{ nextRetryAt: null }, { nextRetryAt: { lte: now } }],
    },
    include: {
      alert: true,
      user: {
        select: {
          id: true,
          email: true,
          deletedAt: true,
        },
      },
    },
    orderBy: [{ nextRetryAt: "asc" }, { createdAt: "asc" }],
    take: limit,
  });
}

export async function processEmailDeliveryAttempt({
  attempt,
  database,
  emailSender,
  maxAttempts = DEFAULT_MAX_DELIVERY_ATTEMPTS,
  now = new Date(),
}: {
  attempt: DeliveryAttemptWithContext;
  database: DeliveryDispatchDatabase;
  emailSender: EmailSender;
  maxAttempts?: number;
  now?: Date;
}): Promise<DeliveryAttemptResult> {
  if (attempt.channel !== AlertChannel.EMAIL) {
    await database.alertDeliveryAttempt.update({
      where: { id: attempt.id },
      data: {
        status: DeliveryStatus.SKIPPED,
        failedAt: now,
        nextRetryAt: null,
        failureCategory: "unexpected",
        failureMessage: `Unsupported delivery channel: ${attempt.channel}`,
      },
    });
    return {
      attemptId: attempt.id,
      status: "skipped",
      failureCategory: "unexpected",
    };
  }

  if (attempt.user.deletedAt || !attempt.user.email.trim()) {
    const error = new DeliveryDispatchError(
      "invalid_recipient",
      "Email delivery skipped because the user is deleted or has no email.",
    );
    await database.alertDeliveryAttempt.update({
      where: { id: attempt.id },
      data: {
        status: DeliveryStatus.SKIPPED,
        failedAt: now,
        nextRetryAt: null,
        failureCategory: error.category,
        failureMessage: error.message,
      },
    });
    return {
      attemptId: attempt.id,
      status: "skipped",
      failureCategory: error.category,
      failureMessage: error.message,
    };
  }

  try {
    const payload = deliveryPayloadForAttempt(attempt);
    const rendered = renderDeliveryEmail(payload);
    const result = await emailSender({
      to: attempt.user.email,
      idempotencyKey: attempt.idempotencyKey ?? attempt.id,
      ...rendered,
    });

    await database.alertDeliveryAttempt.update({
      where: { id: attempt.id },
      data: {
        status: DeliveryStatus.SENT,
        providerMessageId: result.providerMessageId ?? null,
        failedAt: null,
        failureCategory: null,
        failureMessage: null,
        nextRetryAt: null,
      },
    });
    await database.alert.updateMany({
      where: { id: attempt.alert.id, state: AlertState.APPROVED },
      data: { state: AlertState.SENT, sentAt: now },
    });

    return { attemptId: attempt.id, status: "sent" };
  } catch (error) {
    const failureUpdate = buildDeliveryFailureUpdate({
      attemptNumber: attempt.attemptNumber,
      error,
      maxAttempts,
      now,
    });
    await database.alertDeliveryAttempt.update({
      where: { id: attempt.id },
      data: failureUpdate,
    });

    const finalStatus =
      failureUpdate.status === DeliveryStatus.DEAD_LETTER
        ? "dead_letter"
        : "failed";
    return {
      attemptId: attempt.id,
      status: finalStatus,
      failureCategory: classifyDeliveryError(error),
      failureMessage: sanitizeFailureMessage(error),
    };
  }
}

function countResult(
  summary: DeliveryDispatchSummary,
  result: DeliveryAttemptResult,
) {
  if (result.status === "sent") summary.sent += 1;
  if (result.status === "failed") summary.failed += 1;
  if (result.status === "dead_letter") summary.deadLettered += 1;
  if (result.status === "skipped") summary.skipped += 1;
  if (result.status === "error") summary.errors.push(result);
  if (result.status === "failed" || result.status === "dead_letter") {
    summary.errors.push(result);
  }
}

export async function processDueEmailDeliveryAttempts({
  database,
  emailSender,
  limit = 25,
  maxAttempts = DEFAULT_MAX_DELIVERY_ATTEMPTS,
  now = new Date(),
}: {
  database: DeliveryDispatchDatabase;
  emailSender: EmailSender;
  limit?: number;
  maxAttempts?: number;
  now?: Date;
}): Promise<DeliveryDispatchSummary> {
  const attempts = await listDueEmailDeliveryAttempts(database, { limit, now });
  const summary: DeliveryDispatchSummary = {
    checked: attempts.length,
    sent: 0,
    failed: 0,
    deadLettered: 0,
    skipped: 0,
    errors: [],
  };

  for (const attempt of attempts) {
    try {
      const result = await processEmailDeliveryAttempt({
        attempt,
        database,
        emailSender,
        maxAttempts,
        now,
      });
      countResult(summary, result);
    } catch (error) {
      summary.errors.push({
        attemptId: attempt.id,
        status: "error",
        failureCategory: classifyDeliveryError(error),
        failureMessage: sanitizeFailureMessage(error),
      });
    }
  }

  return summary;
}
