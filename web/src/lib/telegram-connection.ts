import { createHmac, randomInt, timingSafeEqual } from "node:crypto";

import { getServerEnv } from "@/lib/env";

export const TELEGRAM_VERIFICATION_TTL_SECONDS = 15 * 60;

export type TelegramWebhookMessage = {
  chatId: string;
  telegramUserId: string | null;
  text: string;
};

function telegramSecret(explicitSecret?: string) {
  const secret =
    explicitSecret ??
    getServerEnv().AUTH_SECRET ??
    getServerEnv().ENGINE_INGEST_SECRET;
  if (!secret || secret.length < 32) {
    throw new Error(
      "A 32+ character secret is required for Telegram verification.",
    );
  }
  return secret;
}

export function generateTelegramVerificationCode() {
  return randomInt(100000, 1000000).toString();
}

export function normalizeTelegramVerificationCode(value: string) {
  const match = value.match(/\b(\d{6})\b/);
  return match?.[1] ?? null;
}

export function hashTelegramVerificationCode({
  userId,
  code,
  secret,
}: {
  userId: string;
  code: string;
  secret?: string;
}) {
  const normalized = normalizeTelegramVerificationCode(code);
  if (!normalized) {
    throw new Error("Telegram verification code must be six digits.");
  }
  return createHmac("sha256", telegramSecret(secret))
    .update(`${userId}:${normalized}`)
    .digest("hex");
}

export function verifyTelegramVerificationCode({
  userId,
  code,
  expectedHash,
  secret,
}: {
  userId: string;
  code: string;
  expectedHash: string;
  secret?: string;
}) {
  const actual = Buffer.from(
    hashTelegramVerificationCode({ userId, code, secret }),
    "hex",
  );
  const expected = Buffer.from(expectedHash, "hex");
  return actual.length === expected.length && timingSafeEqual(actual, expected);
}

export function isTelegramVerificationFresh({
  updatedAt,
  now = new Date(),
  ttlSeconds = TELEGRAM_VERIFICATION_TTL_SECONDS,
}: {
  updatedAt: Date;
  now?: Date;
  ttlSeconds?: number;
}) {
  return now.getTime() - updatedAt.getTime() <= ttlSeconds * 1000;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

export function parseTelegramWebhookMessage(
  payload: unknown,
): TelegramWebhookMessage | null {
  if (!isRecord(payload) || !isRecord(payload.message)) return null;
  const message = payload.message;
  if (!isRecord(message.chat)) return null;
  const text = message.text;
  const chatId = message.chat.id;
  const fromId = isRecord(message.from) ? message.from.id : null;
  if (typeof text !== "string" || !text.trim()) return null;
  if (typeof chatId !== "string" && typeof chatId !== "number") return null;

  return {
    chatId: String(chatId),
    telegramUserId:
      typeof fromId === "string" || typeof fromId === "number"
        ? String(fromId)
        : null,
    text,
  };
}

export function isTelegramWebhookSecretValid({
  received,
  expected,
}: {
  received: string | null;
  expected: string | undefined;
}) {
  if (!expected?.trim() || !received) return false;
  const receivedBuffer = Buffer.from(received);
  const expectedBuffer = Buffer.from(expected);
  return (
    receivedBuffer.length === expectedBuffer.length &&
    timingSafeEqual(receivedBuffer, expectedBuffer)
  );
}
