import { createHmac, timingSafeEqual } from "node:crypto";

import { z } from "zod";

const marketBiasSchema = z.enum(["BULLISH", "BEARISH", "NEUTRAL", "MIXED"]);
const riskLevelSchema = z.enum(["LOW", "MEDIUM", "HIGH", "CRITICAL"]);
const moderationStateSchema = z.enum(["DRAFT", "PENDING"]);
const optionalDateTimeSchema = z.string().trim().min(1).nullable().optional();

const requiredText = z.string().trim().min(1);
const optionalText = z.string().trim().min(1).nullable().optional();

export const ENGINE_INGEST_SIGNATURE_HEADER = "x-market-catalyst-signature";
export const ENGINE_INGEST_TIMESTAMP_HEADER = "x-market-catalyst-timestamp";
export const ENGINE_INGEST_TOLERANCE_SECONDS = 5 * 60;

export const engineIngestPayloadSchema = z
  .object({
    version: z.literal(1),
    idempotencyKey: z.string().trim().min(12).max(180),
    generatedAt: requiredText,
    newsEvent: z
      .object({
        source: z.string().trim().min(1).max(80),
        sourceEventId: z.string().trim().min(1).max(255).nullable().optional(),
        publisher: z.string().trim().min(1).max(120).nullable().optional(),
        symbol: z.string().trim().min(1).max(40).nullable().optional(),
        eventFamily: z.string().trim().min(1).max(80).nullable().optional(),
        headline: requiredText,
        url: z.url().nullable().optional(),
        summary: optionalText,
        occurredAt: optionalDateTimeSchema,
        fetchedAt: optionalDateTimeSchema,
        rawPayload: z.unknown().optional(),
      })
      .strict()
      .optional(),
    marketReaction: z
      .object({
        eventFamily: z.string().trim().min(1).max(80),
        symbol: z.string().trim().min(1).max(40).default("NQ"),
        releaseTime: optionalDateTimeSchema,
        actualValue: z.string().trim().min(1).max(120).nullable().optional(),
        forecastValue: z.string().trim().min(1).max(120).nullable().optional(),
        previousValue: z.string().trim().min(1).max(120).nullable().optional(),
        releaseRuleBias: marketBiasSchema,
        liveRegimeBias: marketBiasSchema,
        finalBias: marketBiasSchema,
        bullishProbability: z.number().min(0).max(100).nullable().optional(),
        confidence: z.number().int().min(0).max(100),
        riskLevel: riskLevelSchema,
        tradeState: z.string().trim().min(1).max(120),
        expectedReaction: requiredText,
        reasoning: requiredText,
        riskWarning: optionalText,
        watchLevels: z.unknown().optional(),
        invalidation: optionalText,
        expiresAt: optionalDateTimeSchema,
      })
      .strict(),
    alert: z
      .object({
        state: moderationStateSchema.default("PENDING"),
        headline: requiredText,
        summary: requiredText,
        bias: marketBiasSchema,
        expectedReaction: requiredText,
        confidence: z.number().int().min(0).max(100),
        riskLevel: riskLevelSchema,
        reasoning: requiredText,
        riskWarning: requiredText,
        watchLevels: z.unknown().optional(),
        invalidation: optionalText,
        disclaimer: requiredText,
        sourceFingerprint: z
          .string()
          .trim()
          .min(12)
          .max(255)
          .nullable()
          .optional(),
        expiresAt: optionalDateTimeSchema,
      })
      .strict(),
  })
  .strict();

export type EngineIngestPayload = z.infer<typeof engineIngestPayloadSchema>;

export type SignatureVerification =
  | { ok: true; timestamp: number }
  | { ok: false; status: number; error: string };

export function parseEngineIngestPayload(value: unknown) {
  return engineIngestPayloadSchema.parse(value);
}

export function parseEngineDate(value: string | null | undefined) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    throw new Error(`Invalid engine timestamp: ${value}`);
  }
  return date;
}

export function signEngineIngestBody(
  secret: string,
  timestamp: number | string,
  body: string,
) {
  const digest = createHmac("sha256", secret)
    .update(`${timestamp}.${body}`)
    .digest("hex");
  return `sha256=${digest}`;
}

function signatureDigest(value: string | null) {
  if (!value) return null;
  const normalized = value.startsWith("sha256=") ? value.slice(7) : value;
  if (!/^[0-9a-f]{64}$/i.test(normalized)) return null;
  return Buffer.from(normalized, "hex");
}

export function verifyEngineIngestSignature({
  secret,
  timestamp,
  body,
  signature,
  now = Date.now(),
  toleranceSeconds = ENGINE_INGEST_TOLERANCE_SECONDS,
}: {
  secret: string | undefined;
  timestamp: string | null;
  body: string;
  signature: string | null;
  now?: number;
  toleranceSeconds?: number;
}): SignatureVerification {
  if (!secret || secret.length < 32) {
    return {
      ok: false,
      status: 503,
      error: "Engine ingestion secret is not configured.",
    };
  }

  const parsedTimestamp = Number(timestamp);
  if (!timestamp || !Number.isFinite(parsedTimestamp)) {
    return {
      ok: false,
      status: 401,
      error: "Missing or invalid ingestion timestamp.",
    };
  }

  const ageSeconds = Math.abs(now / 1000 - parsedTimestamp);
  if (ageSeconds > toleranceSeconds) {
    return {
      ok: false,
      status: 401,
      error: "Ingestion timestamp is outside the replay window.",
    };
  }

  const supplied = signatureDigest(signature);
  const expected = signatureDigest(
    signEngineIngestBody(secret, timestamp, body),
  );
  if (
    !supplied ||
    !expected ||
    supplied.length !== expected.length ||
    !timingSafeEqual(supplied, expected)
  ) {
    return {
      ok: false,
      status: 401,
      error: "Invalid ingestion signature.",
    };
  }

  return { ok: true, timestamp: parsedTimestamp };
}
