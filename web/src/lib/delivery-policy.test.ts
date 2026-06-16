import { describe, expect, it } from "vitest";

import { AlertChannel, MarketBias, RiskLevel } from "@/generated/prisma/enums";
import {
  alertMatchesPreference,
  buildDeliveryPayload,
  enabledDeliveryChannels,
  isDailyLimitAvailable,
  isQuietHoursActive,
  nextRetryAtForPlan,
  retryDelaySeconds,
  type DeliveryAlert,
} from "@/lib/delivery-policy";
import { PLAN_CATALOG } from "@/lib/plan-catalog";

const alert: DeliveryAlert = {
  id: "alert-1",
  headline: "Hot NFP pressures NQ",
  summary: "Labor surprise can lift yields.",
  bias: MarketBias.BEARISH,
  expectedReaction: "Avoid long NQ until tape reclaims.",
  confidence: 82,
  riskLevel: RiskLevel.MEDIUM,
  reasoning: "Hot labor data can renew Fed pressure.",
  riskWarning: "Wait for post-release confirmation.",
  watchLevels: { nq: ["VWAP"] },
  invalidation: "Yields fade and NQ reclaims VWAP.",
  disclaimer: "Educational and informational use only.",
  createdAt: new Date("2026-06-15T13:00:00.000Z"),
  expiresAt: new Date("2026-06-15T15:00:00.000Z"),
  marketReaction: {
    eventFamily: "nfp",
    symbol: "NQ",
  },
};

const preference = {
  emailEnabled: true,
  telegramEnabled: true,
  discordEnabled: true,
  minimumConfidence: 60,
  minimumRiskLevel: RiskLevel.LOW,
  eventFamilies: ["nfp", "cpi"],
  symbols: ["NQ"],
  quietHours: {
    enabled: false,
    start: "16:00",
    end: "08:00",
  },
};

describe("delivery policy", () => {
  it("selects only entitled and verified channels", () => {
    expect(
      enabledDeliveryChannels({
        entitlements: PLAN_CATALOG.basic.entitlements,
        preference,
        verified: { email: true, telegram: true, discord: true },
      }),
    ).toEqual([AlertChannel.EMAIL]);

    expect(
      enabledDeliveryChannels({
        entitlements: PLAN_CATALOG.pro.entitlements,
        preference,
        verified: { email: true, telegram: false, discord: true },
      }),
    ).toEqual([AlertChannel.EMAIL, AlertChannel.DISCORD]);
  });

  it("applies confidence, risk, family, and symbol preferences", () => {
    expect(alertMatchesPreference({ alert, preference })).toBe(true);
    expect(
      alertMatchesPreference({
        alert: { ...alert, confidence: 40 },
        preference,
      }),
    ).toBe(false);
    expect(
      alertMatchesPreference({
        alert: {
          ...alert,
          marketReaction: { eventFamily: "jolts", symbol: "NQ" },
        },
        preference,
      }),
    ).toBe(false);
    expect(
      alertMatchesPreference({
        alert: {
          ...alert,
          marketReaction: { eventFamily: "nfp", symbol: "ES" },
        },
        preference,
      }),
    ).toBe(false);
  });

  it("handles overnight quiet hours in Eastern Time", () => {
    const quietPreference = {
      ...preference,
      quietHours: {
        enabled: true,
        start: "16:00",
        end: "08:00",
      },
    };

    expect(
      isQuietHoursActive(quietPreference, new Date("2026-06-15T03:30:00.000Z")),
    ).toBe(true);
    expect(
      isQuietHoursActive(quietPreference, new Date("2026-06-15T14:30:00.000Z")),
    ).toBe(false);
  });

  it("enforces daily limits and plan delay timing", () => {
    expect(isDailyLimitAvailable(PLAN_CATALOG.basic.entitlements, 4)).toBe(
      true,
    );
    expect(isDailyLimitAvailable(PLAN_CATALOG.basic.entitlements, 5)).toBe(
      false,
    );
    expect(isDailyLimitAvailable(PLAN_CATALOG.pro.entitlements, 50)).toBe(true);

    expect(
      nextRetryAtForPlan(
        PLAN_CATALOG.basic.entitlements,
        new Date("2026-06-15T12:00:00.000Z"),
      ).toISOString(),
    ).toBe("2026-06-15T12:05:00.000Z");
  });

  it("builds the required subscriber payload fields and retry schedule", () => {
    const payload = buildDeliveryPayload(alert);

    expect(payload.headline).toBe(alert.headline);
    expect(payload.marketBias).toBe(MarketBias.BEARISH);
    expect(payload.expectedReaction).toContain("Avoid long");
    expect(payload.confidence).toBe(82);
    expect(payload.riskWarning).toContain("confirmation");
    expect(payload.timestamp).toBe("2026-06-15T13:00:00.000Z");
    expect(payload.expiresAt).toBe("2026-06-15T15:00:00.000Z");
    expect(payload.disclaimer).toContain("Educational");
    expect(retryDelaySeconds(1)).toBe(60);
    expect(retryDelaySeconds(4)).toBe(480);
  });
});
