import { z } from "zod";

function optionalString(minimum = 1) {
  return z.preprocess(
    (value) =>
      typeof value === "string" && value.trim() === "" ? undefined : value,
    z.string().trim().min(minimum).optional(),
  );
}

const serverEnvSchema = z.object({
  NODE_ENV: z
    .enum(["development", "test", "production"])
    .default("development"),
  APP_BASE_URL: z.url().default("http://localhost:3000"),
  DATABASE_URL: optionalString(),
  CATALYST_ENGINE_ROOT: optionalString(),
  ENGINE_INGEST_SECRET: optionalString(32),
  AUTH_SECRET: optionalString(32),
  AUTH_EMAIL_FROM: optionalString(),
  STRIPE_SECRET_KEY: optionalString(),
  STRIPE_WEBHOOK_SECRET: optionalString(),
  RESEND_API_KEY: optionalString(),
  TELEGRAM_BOT_TOKEN: optionalString(),
  DISCORD_WEBHOOK_SECRET: optionalString(),
});

export type ServerEnv = z.infer<typeof serverEnvSchema>;

export function parseServerEnv(
  source: NodeJS.ProcessEnv | Record<string, string | undefined>,
) {
  return serverEnvSchema.parse(source);
}

export function getServerEnv() {
  return parseServerEnv(process.env);
}
