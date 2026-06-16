import { describe, expect, it } from "vitest";

import { AlertChannel, DeliveryStatus } from "@/generated/prisma/enums";
import {
  DeliveryDispatchError,
  buildDeliveryFailureUpdate,
  classifyDeliveryError,
  processDueEmailDeliveryAttempts,
  renderDeliveryEmail,
  sanitizeFailureMessage,
  type DeliveryAttemptWithContext,
  type DeliveryDispatchDatabase,
} from "@/lib/delivery-dispatch";

function attempt(
  id: string,
  overrides: Partial<DeliveryAttemptWithContext> = {},
): DeliveryAttemptWithContext {
  return {
    id,
    channel: AlertChannel.EMAIL,
    status: DeliveryStatus.QUEUED,
    idempotencyKey: `idem-${id}`,
    attemptNumber: 1,
    rawPayload: {
      alertId: `alert-${id}`,
      headline: "Hot NFP pressures NQ",
      summary: "Labor surprise can lift yields.",
      marketBias: "BEARISH",
      expectedReaction: "Avoid long NQ until tape reclaims.",
      confidence: 82,
      riskLevel: "MEDIUM",
      shortReasoning: "Hot labor data can renew Fed pressure.",
      riskWarning: "Wait for post-release confirmation.",
      timestamp: "2026-06-15T13:00:00.000Z",
      expiresAt: "2026-06-15T15:00:00.000Z",
      timeSensitivity: "Expires 2026-06-15T15:00:00.000Z",
      watchLevels: { nq: ["VWAP", "prior low"] },
      invalidation: "Yields fade and NQ reclaims VWAP.",
      disclaimer: "Educational and informational use only.",
    },
    alert: {
      id: `alert-${id}`,
      headline: "Fallback headline",
      summary: "Fallback summary",
      bias: "MIXED",
      expectedReaction: "Fallback reaction",
      confidence: 60,
      riskLevel: "LOW",
      reasoning: "Fallback reasoning",
      riskWarning: "Fallback warning",
      watchLevels: null,
      invalidation: null,
      disclaimer: "Fallback disclaimer",
      createdAt: new Date("2026-06-15T12:00:00.000Z"),
      expiresAt: null,
    },
    user: {
      id: `user-${id}`,
      email: `${id}@example.com`,
      deletedAt: null,
    },
    ...overrides,
  };
}

describe("delivery dispatch", () => {
  it("renders every required subscriber alert field into email text", () => {
    const email = renderDeliveryEmail({
      alertId: "alert-1",
      headline: "Hot NFP pressures NQ",
      summary: "Labor surprise can lift yields.",
      marketBias: "BEARISH",
      expectedReaction: "Avoid long NQ until tape reclaims.",
      confidence: 82,
      riskLevel: "MEDIUM",
      shortReasoning: "Hot labor data can renew Fed pressure.",
      riskWarning: "Wait for post-release confirmation.",
      timestamp: "2026-06-15T13:00:00.000Z",
      expiresAt: "2026-06-15T15:00:00.000Z",
      timeSensitivity: "Expires 2026-06-15T15:00:00.000Z",
      watchLevels: { nq: ["VWAP", "prior low"] },
      invalidation: "Yields fade and NQ reclaims VWAP.",
      disclaimer: "Educational and informational use only.",
    });

    expect(email.subject).toContain("Hot NFP");
    expect(email.text).toContain("Headline: Hot NFP pressures NQ");
    expect(email.text).toContain("Market bias: BEARISH");
    expect(email.text).toContain("Expected reaction: Avoid long NQ");
    expect(email.text).toContain("Confidence: 82%");
    expect(email.text).toContain("Short reasoning: Hot labor data");
    expect(email.text).toContain("Risk warning: Wait");
    expect(email.text).toContain(
      "Expiry / time sensitivity: Expires 2026-06-15T15:00:00.000Z",
    );
    expect(email.text).toContain("Disclaimer: Educational");
  });

  it("classifies and sanitizes provider failures without leaking secrets", () => {
    const error = new DeliveryDispatchError(
      "configuration",
      "Bearer re_secret_token cannot be used.",
    );

    expect(classifyDeliveryError(error)).toBe("configuration");
    expect(sanitizeFailureMessage(error)).not.toContain("re_secret_token");
    expect(classifyDeliveryError(new TypeError("fetch failed"))).toBe(
      "network",
    );
  });

  it("builds retry updates and dead-letters after the max attempt", () => {
    const now = new Date("2026-06-15T12:00:00.000Z");
    const failed = buildDeliveryFailureUpdate({
      attemptNumber: 1,
      error: new DeliveryDispatchError("provider", "temporary failure"),
      now,
    });
    expect(failed.status).toBe(DeliveryStatus.FAILED);
    expect(failed.attemptNumber).toBe(2);
    expect((failed.nextRetryAt as Date).toISOString()).toBe(
      "2026-06-15T12:02:00.000Z",
    );

    const dead = buildDeliveryFailureUpdate({
      attemptNumber: 4,
      error: new DeliveryDispatchError("provider", "final failure"),
      maxAttempts: 5,
      now,
    });
    expect(dead.status).toBe(DeliveryStatus.DEAD_LETTER);
    expect(dead.attemptNumber).toBe(5);
    expect(dead.nextRetryAt).toBeNull();
  });

  it("continues processing after one subscriber delivery fails", async () => {
    const updates: unknown[] = [];
    const database: DeliveryDispatchDatabase = {
      alert: {
        async updateMany(args) {
          updates.push(args);
          return {};
        },
      },
      alertDeliveryAttempt: {
        async findMany() {
          return [attempt("first"), attempt("second")];
        },
        async update(args) {
          updates.push(args);
          return {};
        },
      },
    };

    const summary = await processDueEmailDeliveryAttempts({
      database,
      emailSender: async (message) => {
        if (message.to.startsWith("first")) {
          throw new DeliveryDispatchError("provider", "provider down");
        }
        return { providerMessageId: "resend-second" };
      },
      now: new Date("2026-06-15T12:00:00.000Z"),
    });

    expect(summary.checked).toBe(2);
    expect(summary.failed).toBe(1);
    expect(summary.sent).toBe(1);
    expect(summary.errors[0]?.attemptId).toBe("first");
    expect(updates).toHaveLength(3);
  });
});
