import {
  createCipheriv,
  createDecipheriv,
  createHash,
  randomBytes,
} from "node:crypto";

import { getServerEnv } from "@/lib/env";

export type DiscordWebhookParts = {
  webhookId: string;
  token: string;
};

export class DiscordConnectionError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "DiscordConnectionError";
  }
}

function discordSecret(explicitSecret?: string) {
  const secret =
    explicitSecret ??
    getServerEnv().AUTH_SECRET ??
    getServerEnv().ENGINE_INGEST_SECRET;
  if (!secret || secret.length < 32) {
    throw new Error(
      "A 32+ character secret is required for Discord credentials.",
    );
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

export function parseDiscordWebhookUrl(value: string): DiscordWebhookParts {
  let url: URL;
  try {
    url = new URL(value.trim());
  } catch {
    throw new DiscordConnectionError("Enter a valid Discord webhook URL.");
  }

  const allowedHosts = new Set(["discord.com", "discordapp.com"]);
  if (url.protocol !== "https:" || !allowedHosts.has(url.hostname)) {
    throw new DiscordConnectionError(
      "Discord webhook URL must be an https://discord.com webhook.",
    );
  }

  const parts = url.pathname.split("/").filter(Boolean);
  const webhookIndex = parts.indexOf("webhooks");
  const webhookId = webhookIndex >= 0 ? parts[webhookIndex + 1] : undefined;
  const token = webhookIndex >= 0 ? parts[webhookIndex + 2] : undefined;
  if (!webhookId || !/^\d{15,25}$/.test(webhookId)) {
    throw new DiscordConnectionError("Discord webhook ID was not recognized.");
  }
  if (!token || !/^[A-Za-z0-9._-]{20,}$/.test(token)) {
    throw new DiscordConnectionError(
      "Discord webhook token was not recognized.",
    );
  }

  return { webhookId, token };
}

export function encryptDiscordWebhookToken({
  token,
  secret,
}: {
  token: string;
  secret?: string;
}) {
  const iv = randomBytes(12);
  const cipher = createCipheriv(
    "aes-256-gcm",
    encryptionKey(discordSecret(secret)),
    iv,
  );
  const encrypted = Buffer.concat([
    cipher.update(token, "utf-8"),
    cipher.final(),
  ]);
  return `${encode(iv)}.${encode(cipher.getAuthTag())}.${encode(encrypted)}`;
}

export function decryptDiscordWebhookToken({
  encrypted,
  secret,
}: {
  encrypted: string;
  secret?: string;
}) {
  const [ivText, tagText, encryptedText] = encrypted.split(".");
  if (!ivText || !tagText || !encryptedText) {
    throw new Error("Invalid encrypted Discord token.");
  }
  const decipher = createDecipheriv(
    "aes-256-gcm",
    encryptionKey(discordSecret(secret)),
    decode(ivText),
  );
  decipher.setAuthTag(decode(tagText));
  return Buffer.concat([
    decipher.update(decode(encryptedText)),
    decipher.final(),
  ]).toString("utf-8");
}

export function maskDiscordWebhookId(webhookId: string | null | undefined) {
  if (!webhookId) return null;
  return `${webhookId.slice(0, 4)}...${webhookId.slice(-4)}`;
}

export async function sendDiscordWebhookTest({
  webhookId,
  token,
  fetchFn = fetch,
}: DiscordWebhookParts & {
  fetchFn?: typeof fetch;
}) {
  const response = await fetchFn(
    `https://discord.com/api/webhooks/${webhookId}/${token}?wait=true`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: "Market Catalyst",
        content:
          "Market Catalyst Discord alerts are connected. This is a verification message.",
        allowed_mentions: { parse: [] },
      }),
    },
  );

  if (!response.ok) {
    throw new DiscordConnectionError(
      `Discord rejected the webhook test with HTTP ${response.status}.`,
    );
  }
}
