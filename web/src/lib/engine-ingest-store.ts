import "server-only";

import { createHash } from "node:crypto";

import { AlertState, type Prisma } from "@/generated/prisma/client";
import {
  type EngineIngestPayload,
  parseEngineDate,
} from "@/lib/engine-ingest-contract";
import { getRequiredDatabase } from "@/lib/db";

function jsonValue(value: unknown) {
  return value === undefined ? undefined : (value as Prisma.InputJsonValue);
}

function sourceFingerprintFor(payload: EngineIngestPayload) {
  if (payload.alert.sourceFingerprint) return payload.alert.sourceFingerprint;
  const digest = createHash("sha256")
    .update(payload.idempotencyKey)
    .digest("hex");
  return `engine:${digest}`;
}

export async function persistEngineIngestPayload(payload: EngineIngestPayload) {
  const database = getRequiredDatabase();
  const sourceFingerprint = sourceFingerprintFor(payload);
  const existing = await database.alert.findFirst({
    where: {
      OR: [{ idempotencyKey: payload.idempotencyKey }, { sourceFingerprint }],
    },
    select: {
      id: true,
      marketReactionId: true,
      marketReaction: { select: { newsEventId: true } },
    },
  });

  if (existing) {
    return {
      duplicate: true,
      alertId: existing.id,
      marketReactionId: existing.marketReactionId,
      newsEventId: existing.marketReaction?.newsEventId ?? null,
    };
  }

  return database.$transaction(async (transaction) => {
    let newsEventId: string | null = null;

    if (payload.newsEvent) {
      const newsEventData = {
        source: payload.newsEvent.source,
        sourceEventId: payload.newsEvent.sourceEventId ?? null,
        publisher: payload.newsEvent.publisher ?? null,
        symbol: payload.newsEvent.symbol ?? null,
        eventFamily: payload.newsEvent.eventFamily ?? null,
        headline: payload.newsEvent.headline,
        url: payload.newsEvent.url ?? null,
        summary: payload.newsEvent.summary ?? null,
        occurredAt: parseEngineDate(payload.newsEvent.occurredAt),
        fetchedAt:
          parseEngineDate(payload.newsEvent.fetchedAt) ??
          parseEngineDate(payload.generatedAt) ??
          new Date(),
        rawPayload: jsonValue(payload.newsEvent.rawPayload),
      };

      const newsEvent = payload.newsEvent.sourceEventId
        ? await transaction.newsEvent.upsert({
            where: {
              source_sourceEventId: {
                source: payload.newsEvent.source,
                sourceEventId: payload.newsEvent.sourceEventId,
              },
            },
            update: newsEventData,
            create: newsEventData,
            select: { id: true },
          })
        : await transaction.newsEvent.create({
            data: newsEventData,
            select: { id: true },
          });
      newsEventId = newsEvent.id;
    }

    const marketReaction = await transaction.marketReaction.create({
      data: {
        newsEventId,
        eventFamily: payload.marketReaction.eventFamily,
        symbol: payload.marketReaction.symbol,
        releaseTime: parseEngineDate(payload.marketReaction.releaseTime),
        actualValue: payload.marketReaction.actualValue ?? null,
        forecastValue: payload.marketReaction.forecastValue ?? null,
        previousValue: payload.marketReaction.previousValue ?? null,
        releaseRuleBias: payload.marketReaction.releaseRuleBias,
        liveRegimeBias: payload.marketReaction.liveRegimeBias,
        finalBias: payload.marketReaction.finalBias,
        bullishProbability: payload.marketReaction.bullishProbability ?? null,
        confidence: payload.marketReaction.confidence,
        riskLevel: payload.marketReaction.riskLevel,
        tradeState: payload.marketReaction.tradeState,
        expectedReaction: payload.marketReaction.expectedReaction,
        reasoning: payload.marketReaction.reasoning,
        riskWarning: payload.marketReaction.riskWarning ?? null,
        watchLevels: jsonValue(payload.marketReaction.watchLevels),
        invalidation: payload.marketReaction.invalidation ?? null,
        expiresAt: parseEngineDate(payload.marketReaction.expiresAt),
      },
      select: { id: true },
    });

    const alert = await transaction.alert.create({
      data: {
        marketReactionId: marketReaction.id,
        state: payload.alert.state as AlertState,
        headline: payload.alert.headline,
        summary: payload.alert.summary,
        bias: payload.alert.bias,
        expectedReaction: payload.alert.expectedReaction,
        confidence: payload.alert.confidence,
        riskLevel: payload.alert.riskLevel,
        reasoning: payload.alert.reasoning,
        riskWarning: payload.alert.riskWarning,
        watchLevels: jsonValue(payload.alert.watchLevels),
        invalidation: payload.alert.invalidation ?? null,
        disclaimer: payload.alert.disclaimer,
        sourceFingerprint,
        idempotencyKey: payload.idempotencyKey,
        expiresAt: parseEngineDate(payload.alert.expiresAt),
      },
      select: { id: true },
    });

    return {
      duplicate: false,
      alertId: alert.id,
      marketReactionId: marketReaction.id,
      newsEventId,
    };
  });
}
