import { describe, expect, it } from "vitest";

import {
  parseEngineDate,
  parseEngineIngestPayload,
  signEngineIngestBody,
  verifyEngineIngestSignature,
  type EngineIngestPayload,
} from "@/lib/engine-ingest-contract";

const secret = "0123456789abcdef0123456789abcdef";
const timestamp = 1_800_000_000;

function samplePayload(): EngineIngestPayload {
  return {
    version: 1,
    idempotencyKey: "python-engine:test-ingest-key",
    generatedAt: "2026-06-15T14:00:00.000Z",
    newsEvent: {
      source: "python_engine",
      sourceEventId: "event-1",
      publisher: "TradingView",
      symbol: "NQ",
      eventFamily: "nfp",
      headline: "NFP surprise pressures growth",
      url: "https://example.com/event",
      summary: "Hot labor data can lift rate pressure.",
      occurredAt: "2026-06-15T12:30:00.000Z",
      rawPayload: { actual: "172K" },
    },
    marketReaction: {
      eventFamily: "nfp",
      symbol: "NQ",
      releaseTime: "2026-06-15T12:30:00.000Z",
      actualValue: "172K",
      forecastValue: "80K",
      previousValue: "179K",
      releaseRuleBias: "BEARISH",
      liveRegimeBias: "BEARISH",
      finalBias: "BEARISH",
      bullishProbability: 22,
      confidence: 82,
      riskLevel: "MEDIUM",
      tradeState: "no_long_wait_for_reclaim",
      expectedReaction: "Avoid long NQ until tape reclaims.",
      reasoning: "Hot payrolls can renew Fed pressure.",
      riskWarning: "Wait for confirmation.",
      watchLevels: { nq: ["VWAP"] },
      invalidation: "Yields fade and NQ reclaims VWAP.",
      expiresAt: "2026-06-15T14:30:00.000Z",
    },
    alert: {
      state: "PENDING",
      headline: "Hot NFP pressures NQ",
      summary: "Growth can stay under pressure until yields cool.",
      bias: "BEARISH",
      expectedReaction: "Avoid long NQ until tape reclaims.",
      confidence: 82,
      riskLevel: "MEDIUM",
      reasoning: "Hot payrolls can renew Fed pressure.",
      riskWarning: "Wait for confirmation.",
      watchLevels: { nq: ["VWAP"] },
      invalidation: "Yields fade and NQ reclaims VWAP.",
      disclaimer: "Educational and informational use only.",
      sourceFingerprint: "python-engine:test-fingerprint",
      expiresAt: "2026-06-15T14:30:00.000Z",
    },
  };
}

describe("engine ingestion contract", () => {
  it("accepts a complete canonical payload", () => {
    const payload = parseEngineIngestPayload(samplePayload());

    expect(payload.version).toBe(1);
    expect(payload.alert.state).toBe("PENDING");
    expect(payload.marketReaction.finalBias).toBe("BEARISH");
  });

  it("defaults alert state to pending", () => {
    const payload: unknown = samplePayload();
    const mutable = payload as { alert: { state?: string } };
    delete mutable.alert.state;

    expect(parseEngineIngestPayload(payload).alert.state).toBe("PENDING");
  });

  it("rejects invalid confidence and bias values", () => {
    const payload = samplePayload();
    payload.alert.confidence = 101;
    payload.marketReaction.finalBias = "DOWN" as "BEARISH";

    expect(() => parseEngineIngestPayload(payload)).toThrow();
  });

  it("parses valid timestamps and rejects invalid timestamps", () => {
    expect(parseEngineDate("2026-06-15T12:30:00.000Z")?.toISOString()).toBe(
      "2026-06-15T12:30:00.000Z",
    );
    expect(() => parseEngineDate("not-a-date")).toThrow(
      "Invalid engine timestamp",
    );
  });

  it("verifies HMAC signatures inside the replay window", () => {
    const body = JSON.stringify(samplePayload());
    const signature = signEngineIngestBody(secret, timestamp, body);

    expect(
      verifyEngineIngestSignature({
        secret,
        timestamp: String(timestamp),
        body,
        signature,
        now: timestamp * 1000 + 10_000,
      }).ok,
    ).toBe(true);
  });

  it("rejects stale and mismatched signatures", () => {
    const body = JSON.stringify(samplePayload());
    const signature = signEngineIngestBody(secret, timestamp, body);

    expect(
      verifyEngineIngestSignature({
        secret,
        timestamp: String(timestamp),
        body,
        signature,
        now: timestamp * 1000 + 600_000,
      }),
    ).toMatchObject({ ok: false, status: 401 });
    expect(
      verifyEngineIngestSignature({
        secret,
        timestamp: String(timestamp),
        body: `${body} `,
        signature,
        now: timestamp * 1000,
      }),
    ).toMatchObject({ ok: false, status: 401 });
  });
});
