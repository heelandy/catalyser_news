import {
  createCipheriv,
  createDecipheriv,
  createHash,
  randomBytes,
} from "node:crypto";

import { getServerEnv } from "@/lib/env";

export const PROTECTED_FORM_TOKEN_FIELD = "__protectedFormToken";
export const PROTECTED_FORM_SCOPES = {
  magicLink: "sign-in:magic-link",
  accountPreferences: "account:preferences",
  accountTelegramConnect: "account:telegram-connect",
  accountTelegramDisconnect: "account:telegram-disconnect",
  accountDiscordConnect: "account:discord-connect",
  accountDiscordDisconnect: "account:discord-disconnect",
  adminAlertReview: "admin:alert-review",
  adminIntegrationSettings: "admin:integration-settings",
} as const;

type ProtectedFormPayload = {
  version: 1;
  scope: string;
  userId: string | null;
  issuedAt: number;
  expiresAt: number;
  nonce: string;
};

function formSecret(explicitSecret?: string) {
  const secret =
    explicitSecret ??
    getServerEnv().AUTH_SECRET ??
    getServerEnv().ENGINE_INGEST_SECRET;
  if (!secret || secret.length < 32) {
    throw new Error("A 32+ character secret is required for protected forms.");
  }
  return secret;
}

function encryptionKey(secret: string) {
  return createHash("sha256").update(secret).digest();
}

function encode(value: Buffer) {
  return value.toString("base64url");
}

function decode(value: string) {
  return Buffer.from(value, "base64url");
}

function decryptToken(token: string, secret: string) {
  const [ivText, tagText, encryptedText] = token.split(".");
  if (!ivText || !tagText || !encryptedText) {
    throw new Error("Invalid protected form token.");
  }

  const decipher = createDecipheriv(
    "aes-256-gcm",
    encryptionKey(secret),
    decode(ivText),
  );
  decipher.setAuthTag(decode(tagText));
  const decrypted = Buffer.concat([
    decipher.update(decode(encryptedText)),
    decipher.final(),
  ]);
  return JSON.parse(decrypted.toString("utf-8")) as ProtectedFormPayload;
}

export function createProtectedFormToken({
  scope,
  userId = null,
  ttlSeconds = 15 * 60,
  now = Date.now(),
  secret,
}: {
  scope: string;
  userId?: string | null;
  ttlSeconds?: number;
  now?: number;
  secret?: string;
}) {
  const iv = randomBytes(12);
  const payload: ProtectedFormPayload = {
    version: 1,
    scope,
    userId,
    issuedAt: Math.floor(now / 1000),
    expiresAt: Math.floor(now / 1000) + ttlSeconds,
    nonce: randomBytes(16).toString("hex"),
  };
  const cipher = createCipheriv(
    "aes-256-gcm",
    encryptionKey(formSecret(secret)),
    iv,
  );
  const encrypted = Buffer.concat([
    cipher.update(JSON.stringify(payload), "utf-8"),
    cipher.final(),
  ]);
  return `${encode(iv)}.${encode(cipher.getAuthTag())}.${encode(encrypted)}`;
}

export function verifyProtectedFormToken(
  formData: FormData,
  {
    scope,
    userId = null,
    now = Date.now(),
    secret,
  }: {
    scope: string;
    userId?: string | null;
    now?: number;
    secret?: string;
  },
) {
  const token = formData.get(PROTECTED_FORM_TOKEN_FIELD);
  if (typeof token !== "string" || !token) {
    throw new Error("Missing protected form token.");
  }

  const payload = decryptToken(token, formSecret(secret));
  if (payload.version !== 1 || payload.scope !== scope) {
    throw new Error("Protected form token scope mismatch.");
  }
  if ((payload.userId ?? null) !== (userId ?? null)) {
    throw new Error("Protected form token user mismatch.");
  }
  if (payload.expiresAt < Math.floor(now / 1000)) {
    throw new Error("Protected form token expired.");
  }
  return payload;
}
