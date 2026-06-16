import "server-only";

import { createHash } from "node:crypto";

import { getRequiredDatabase } from "@/lib/db";
import { evaluateAuthRateLimit } from "@/lib/auth-rate-limit-policy";

export class AuthRateLimitError extends Error {
  readonly retryAfterSeconds: number;

  constructor(retryAfterSeconds: number) {
    super(`Too many sign-in requests. Retry in ${retryAfterSeconds} seconds.`);
    this.name = "AuthRateLimitError";
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

function identifierKey(identifier: string) {
  return createHash("sha256")
    .update(identifier.trim().toLowerCase())
    .digest("hex");
}

export async function enforceMagicLinkRateLimit(identifier: string) {
  const database = getRequiredDatabase();
  const key = identifierKey(identifier);
  const now = new Date();

  const decision = await database.$transaction(async (transaction) => {
    const current = await transaction.authRateLimit.findUnique({
      where: { key },
    });
    const next = evaluateAuthRateLimit(current, now);

    await transaction.authRateLimit.upsert({
      where: { key },
      create: { key, ...next.nextState },
      update: next.nextState,
    });

    return next;
  });

  if (!decision.allowed) {
    throw new AuthRateLimitError(decision.retryAfterSeconds);
  }
}
