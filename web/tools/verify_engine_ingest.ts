import { PrismaPg } from "@prisma/adapter-pg";
import { config } from "dotenv";

import { PrismaClient } from "../src/generated/prisma/client";
import {
  signEngineIngestBody,
  type EngineIngestPayload,
} from "../src/lib/engine-ingest-contract";

config({ path: ".env.local" });
config();

const baseUrl = process.env.DASHBOARD_VERIFY_URL ?? "http://127.0.0.1:3000";
const secret = process.env.ENGINE_INGEST_SECRET;
const databaseUrl = process.env.DATABASE_URL;
const suffix = Date.now().toString(36);
const idempotencyKey = `verify-engine-ingest-${suffix}`;
const sourceEventId = `verify-engine-event-${suffix}`;
const sourceFingerprint = `verify-engine-alert-${suffix}`;

if (!databaseUrl) {
  throw new Error("Set DATABASE_URL before verifying engine ingestion.");
}
if (!secret || secret.length < 32) {
  throw new Error(
    "Set ENGINE_INGEST_SECRET with at least 32 characters before verification.",
  );
}

const prisma = new PrismaClient({
  adapter: new PrismaPg({ connectionString: databaseUrl }),
});

function payload(): EngineIngestPayload {
  const now = new Date();
  const expiresAt = new Date(now.getTime() + 2 * 60 * 60 * 1000);

  return {
    version: 1,
    idempotencyKey,
    generatedAt: now.toISOString(),
    newsEvent: {
      source: "verify_engine",
      sourceEventId,
      publisher: "local",
      symbol: "NQ",
      eventFamily: "fomc",
      headline: "Verification FOMC headline",
      summary: "Synthetic engine ingestion verification event.",
      occurredAt: now.toISOString(),
      rawPayload: { verify: true },
    },
    marketReaction: {
      eventFamily: "fomc",
      symbol: "NQ",
      releaseTime: now.toISOString(),
      actualValue: "3.625%",
      forecastValue: "3.625%",
      previousValue: "3.625%",
      releaseRuleBias: "NEUTRAL",
      liveRegimeBias: "BULLISH",
      finalBias: "MIXED",
      bullishProbability: 58,
      confidence: 72,
      riskLevel: "MEDIUM",
      tradeState: "long_only_after_confirmation",
      expectedReaction: "Wait for NQ confirmation around the FOMC reaction.",
      reasoning:
        "Neutral release with bullish tape still requires confirmation.",
      riskWarning: "Do not trade before the first reaction stabilizes.",
      watchLevels: { nq: ["VWAP", "opening range"] },
      invalidation: "Regime turns bearish or NQ loses VWAP.",
      expiresAt: expiresAt.toISOString(),
    },
    alert: {
      state: "PENDING",
      headline: "FOMC reaction requires confirmation",
      summary: "Neutral release with bullish tape should wait for NQ reclaim.",
      bias: "MIXED",
      expectedReaction: "Wait for NQ confirmation around the FOMC reaction.",
      confidence: 72,
      riskLevel: "MEDIUM",
      reasoning:
        "Neutral release with bullish tape still requires confirmation.",
      riskWarning: "Do not trade before the first reaction stabilizes.",
      watchLevels: { nq: ["VWAP", "opening range"] },
      invalidation: "Regime turns bearish or NQ loses VWAP.",
      disclaimer: "Educational and informational use only.",
      sourceFingerprint,
      expiresAt: expiresAt.toISOString(),
    },
  };
}

async function postSigned(body: string) {
  const timestamp = Math.floor(Date.now() / 1000);
  const response = await fetch(`${baseUrl}/api/engine/alerts`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-market-catalyst-timestamp": String(timestamp),
      "x-market-catalyst-signature": signEngineIngestBody(
        secret!,
        timestamp,
        body,
      ),
    },
    body,
  });
  const json = (await response.json()) as {
    ok?: boolean;
    duplicate?: boolean;
    alertId?: string;
    marketReactionId?: string;
    newsEventId?: string;
    error?: string;
  };
  if (!response.ok || !json.ok) {
    throw new Error(
      `Engine ingestion failed with ${response.status}: ${JSON.stringify(json)}`,
    );
  }
  return { status: response.status, json };
}

async function cleanup(ids?: {
  alertId?: string;
  marketReactionId?: string | null;
  newsEventId?: string | null;
}) {
  if (ids?.alertId) {
    await prisma.alert.delete({ where: { id: ids.alertId } }).catch(() => null);
  } else {
    await prisma.alert
      .deleteMany({ where: { idempotencyKey } })
      .catch(() => null);
  }
  if (ids?.marketReactionId) {
    await prisma.marketReaction
      .delete({ where: { id: ids.marketReactionId } })
      .catch(() => null);
  }
  if (ids?.newsEventId) {
    await prisma.newsEvent
      .delete({ where: { id: ids.newsEventId } })
      .catch(() => null);
  }
  await prisma.newsEvent
    .deleteMany({ where: { source: "verify_engine", sourceEventId } })
    .catch(() => null);
}

async function main() {
  let ids:
    | {
        alertId?: string;
        marketReactionId?: string | null;
        newsEventId?: string | null;
      }
    | undefined;

  try {
    const body = JSON.stringify(payload());
    const first = await postSigned(body);
    if (first.status !== 201 || first.json.duplicate) {
      throw new Error(
        `Expected first ingestion to create records: ${first.status}`,
      );
    }
    ids = {
      alertId: first.json.alertId,
      marketReactionId: first.json.marketReactionId,
      newsEventId: first.json.newsEventId,
    };

    const second = await postSigned(body);
    if (second.status !== 200 || !second.json.duplicate) {
      throw new Error("Expected duplicate ingestion to be idempotent.");
    }

    const alert = await prisma.alert.findUnique({
      where: { id: first.json.alertId },
      include: {
        marketReaction: { include: { newsEvent: true } },
      },
    });
    if (
      !alert ||
      alert.state !== "PENDING" ||
      alert.marketReaction?.newsEvent?.sourceEventId !== sourceEventId
    ) {
      throw new Error("Persisted engine ingestion records did not match.");
    }

    console.log("Engine ingestion verification passed.");
  } finally {
    await cleanup(ids);
    await prisma.$disconnect();
  }
}

main().catch(async (error) => {
  await cleanup();
  await prisma.$disconnect();
  throw error;
});
