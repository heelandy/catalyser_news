import { describe, expect, it } from "vitest";

import { parseServerEnv } from "@/lib/env";

describe("server environment", () => {
  it("uses safe local foundation defaults", () => {
    const env = parseServerEnv({ NODE_ENV: "test" });
    expect(env.APP_BASE_URL).toBe("http://localhost:3000");
    expect(env.DATABASE_URL).toBeUndefined();
  });

  it("rejects invalid public URLs", () => {
    expect(() => parseServerEnv({ APP_BASE_URL: "not-a-url" })).toThrow();
  });

  it("requires long secrets when optional secrets are supplied", () => {
    expect(() => parseServerEnv({ AUTH_SECRET: "short" })).toThrow();
  });

  it("treats blank optional values from .env.local as unset", () => {
    const env = parseServerEnv({
      DATABASE_URL: "",
      ENGINE_INGEST_SECRET: "",
      AUTH_SECRET: "   ",
      AUTH_EMAIL_FROM: "",
      STRIPE_SECRET_KEY: "",
      STRIPE_WEBHOOK_SECRET: "",
      RESEND_API_KEY: "",
      TELEGRAM_BOT_TOKEN: "",
      TELEGRAM_BOT_USERNAME: "",
      TELEGRAM_WEBHOOK_SECRET: "",
      DISCORD_WEBHOOK_SECRET: "",
    });

    expect(env.DATABASE_URL).toBeUndefined();
    expect(env.ENGINE_INGEST_SECRET).toBeUndefined();
    expect(env.AUTH_SECRET).toBeUndefined();
    expect(env.AUTH_EMAIL_FROM).toBeUndefined();
    expect(env.STRIPE_SECRET_KEY).toBeUndefined();
    expect(env.STRIPE_WEBHOOK_SECRET).toBeUndefined();
    expect(env.RESEND_API_KEY).toBeUndefined();
    expect(env.TELEGRAM_BOT_TOKEN).toBeUndefined();
    expect(env.TELEGRAM_BOT_USERNAME).toBeUndefined();
    expect(env.TELEGRAM_WEBHOOK_SECRET).toBeUndefined();
    expect(env.DISCORD_WEBHOOK_SECRET).toBeUndefined();
  });
});
