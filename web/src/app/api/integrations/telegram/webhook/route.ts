import { NextResponse } from "next/server";

import { getRequiredDatabase } from "@/lib/db";
import { getServerEnv } from "@/lib/env";
import {
  isTelegramVerificationFresh,
  isTelegramWebhookSecretValid,
  normalizeTelegramVerificationCode,
  parseTelegramWebhookMessage,
  verifyTelegramVerificationCode,
} from "@/lib/telegram-connection";

export const runtime = "nodejs";

export async function POST(request: Request) {
  const env = getServerEnv();
  if (!env.TELEGRAM_WEBHOOK_SECRET) {
    return NextResponse.json(
      { ok: false, error: "telegram_webhook_not_configured" },
      { status: 503 },
    );
  }

  if (
    !isTelegramWebhookSecretValid({
      received: request.headers.get("x-telegram-bot-api-secret-token"),
      expected: env.TELEGRAM_WEBHOOK_SECRET,
    })
  ) {
    return NextResponse.json(
      { ok: false, error: "invalid_telegram_webhook_secret" },
      { status: 403 },
    );
  }

  const payload = (await request.json().catch(() => null)) as unknown;
  const message = parseTelegramWebhookMessage(payload);
  if (!message) {
    return NextResponse.json({ ok: true, verified: false });
  }

  const code = normalizeTelegramVerificationCode(message.text);
  if (!code) {
    return NextResponse.json({ ok: true, verified: false });
  }

  const now = new Date();
  const database = getRequiredDatabase();
  const candidates = await database.telegramConnection.findMany({
    where: {
      disabledAt: null,
      verifiedAt: null,
      verificationCodeHash: { not: null },
    },
    orderBy: { updatedAt: "desc" },
    take: 100,
  });
  const match = candidates.find(
    (candidate) =>
      candidate.verificationCodeHash &&
      isTelegramVerificationFresh({ updatedAt: candidate.updatedAt, now }) &&
      verifyTelegramVerificationCode({
        userId: candidate.userId,
        code,
        expectedHash: candidate.verificationCodeHash,
      }),
  );

  if (!match) {
    return NextResponse.json({ ok: true, verified: false });
  }

  const existingChat = await database.telegramConnection.findFirst({
    where: {
      chatId: message.chatId,
      disabledAt: null,
      NOT: { id: match.id },
    },
    select: { id: true, userId: true },
  });
  if (existingChat && existingChat.userId !== match.userId) {
    return NextResponse.json({
      ok: true,
      verified: false,
      error: "telegram_chat_already_connected",
    });
  }

  await database.telegramConnection.update({
    where: { id: match.id },
    data: {
      chatId: message.chatId,
      telegramUserId: message.telegramUserId,
      verificationCodeHash: null,
      verifiedAt: now,
      disabledAt: null,
    },
  });

  return NextResponse.json({ ok: true, verified: true });
}
