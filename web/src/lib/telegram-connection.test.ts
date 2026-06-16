import { describe, expect, it } from "vitest";

import {
  hashTelegramVerificationCode,
  isTelegramVerificationFresh,
  isTelegramWebhookSecretValid,
  normalizeTelegramVerificationCode,
  parseTelegramWebhookMessage,
  verifyTelegramVerificationCode,
} from "@/lib/telegram-connection";

const secret = "local-telegram-secret-0123456789abcdef";

describe("telegram connection helpers", () => {
  it("normalizes a six-digit verification code from plain or command text", () => {
    expect(normalizeTelegramVerificationCode("123456")).toBe("123456");
    expect(normalizeTelegramVerificationCode("/start 654321")).toBe("654321");
    expect(normalizeTelegramVerificationCode("no code")).toBeNull();
  });

  it("stores and verifies only an HMAC hash of the Telegram code", () => {
    const expectedHash = hashTelegramVerificationCode({
      userId: "user-1",
      code: "123456",
      secret,
    });

    expect(expectedHash).not.toContain("123456");
    expect(
      verifyTelegramVerificationCode({
        userId: "user-1",
        code: "123456",
        expectedHash,
        secret,
      }),
    ).toBe(true);
    expect(
      verifyTelegramVerificationCode({
        userId: "user-2",
        code: "123456",
        expectedHash,
        secret,
      }),
    ).toBe(false);
  });

  it("enforces the verification freshness window", () => {
    expect(
      isTelegramVerificationFresh({
        updatedAt: new Date("2026-06-16T12:00:00.000Z"),
        now: new Date("2026-06-16T12:14:59.000Z"),
      }),
    ).toBe(true);
    expect(
      isTelegramVerificationFresh({
        updatedAt: new Date("2026-06-16T12:00:00.000Z"),
        now: new Date("2026-06-16T12:15:01.000Z"),
      }),
    ).toBe(false);
  });

  it("parses the Telegram webhook message fields needed for ownership proof", () => {
    expect(
      parseTelegramWebhookMessage({
        message: {
          text: "/start 123456",
          chat: { id: -100123 },
          from: { id: 456 },
        },
      }),
    ).toEqual({
      text: "/start 123456",
      chatId: "-100123",
      telegramUserId: "456",
    });
    expect(parseTelegramWebhookMessage({ message: { text: "123456" } })).toBe(
      null,
    );
  });

  it("compares Telegram webhook secrets without accepting missing values", () => {
    expect(
      isTelegramWebhookSecretValid({
        received: "webhook-secret-0123456789abcdef",
        expected: "webhook-secret-0123456789abcdef",
      }),
    ).toBe(true);
    expect(
      isTelegramWebhookSecretValid({
        received: "wrong-secret",
        expected: "webhook-secret-0123456789abcdef",
      }),
    ).toBe(false);
    expect(
      isTelegramWebhookSecretValid({
        received: null,
        expected: "webhook-secret-0123456789abcdef",
      }),
    ).toBe(false);
  });
});
