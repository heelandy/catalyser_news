import { describe, expect, it } from "vitest";

import {
  decryptDiscordWebhookToken,
  encryptDiscordWebhookToken,
  maskDiscordWebhookId,
  parseDiscordWebhookUrl,
  sendDiscordWebhookTest,
} from "@/lib/discord-connection";

const secret = "local-discord-secret-0123456789abcdef";
const webhookUrl =
  "https://discord.com/api/webhooks/123456789012345678/test_token.abc-1234567890_abcdef";

describe("discord connection helpers", () => {
  it("parses Discord webhook URLs without exposing token in the ID", () => {
    expect(parseDiscordWebhookUrl(webhookUrl)).toEqual({
      webhookId: "123456789012345678",
      token: "test_token.abc-1234567890_abcdef",
    });
    expect(() =>
      parseDiscordWebhookUrl("http://discord.com/api/webhooks/1/a"),
    ).toThrow();
    expect(() =>
      parseDiscordWebhookUrl("https://example.com/webhooks/1/a"),
    ).toThrow();
  });

  it("encrypts and decrypts the webhook token without storing plaintext", () => {
    const encrypted = encryptDiscordWebhookToken({
      token: "test_token.abc-1234567890_abcdef",
      secret,
    });

    expect(encrypted).not.toContain("test_token");
    expect(decryptDiscordWebhookToken({ encrypted, secret })).toBe(
      "test_token.abc-1234567890_abcdef",
    );
  });

  it("masks readable webhook identifiers", () => {
    expect(maskDiscordWebhookId("123456789012345678")).toBe("1234...5678");
    expect(maskDiscordWebhookId(null)).toBeNull();
  });

  it("sends a verification message and rejects provider failures", async () => {
    const calls: unknown[] = [];
    await sendDiscordWebhookTest({
      webhookId: "123456789012345678",
      token: "test_token.abc-1234567890_abcdef",
      fetchFn: async (url, init) => {
        calls.push({ url, init });
        return new Response("{}", { status: 200 });
      },
    });
    expect(calls).toHaveLength(1);

    await expect(
      sendDiscordWebhookTest({
        webhookId: "123456789012345678",
        token: "test_token.abc-1234567890_abcdef",
        fetchFn: async () => new Response("no", { status: 404 }),
      }),
    ).rejects.toThrow("Discord rejected");
  });
});
