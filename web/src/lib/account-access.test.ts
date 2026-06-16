import { describe, expect, it } from "vitest";

import { AlertChannel, AlertState } from "@/generated/prisma/enums";
import { canViewAlert } from "@/lib/account-access";
import { parseAlertPreferenceForm } from "@/lib/account-preferences";
import type { PlanEntitlements } from "@/lib/plan-catalog";

const baseEntitlements: PlanEntitlements = {
  accountAccess: true,
  summaryDelayMinutes: 30,
  dailyAlertLimit: 0,
  alertHistoryDays: 1,
  channels: [AlertChannel.EMAIL],
  realtimeAlerts: false,
  fullAnalysis: false,
  preferences: false,
  priorityAlerts: false,
  nqPriority: false,
  premiumCommunity: false,
};

describe("account alert visibility", () => {
  it("delays free-plan alert visibility", () => {
    const alert = {
      state: AlertState.SENT,
      createdAt: new Date("2026-06-15T14:00:00.000Z"),
      sentAt: new Date("2026-06-15T14:00:00.000Z"),
    };

    expect(
      canViewAlert(
        alert,
        baseEntitlements,
        new Date("2026-06-15T14:20:00.000Z"),
      ),
    ).toBe(false);
    expect(
      canViewAlert(
        alert,
        baseEntitlements,
        new Date("2026-06-15T14:31:00.000Z"),
      ),
    ).toBe(true);
  });

  it("hides alerts outside the plan history window", () => {
    const alert = {
      state: AlertState.SENT,
      createdAt: new Date("2026-06-13T14:00:00.000Z"),
      sentAt: new Date("2026-06-13T14:00:00.000Z"),
    };

    expect(
      canViewAlert(
        alert,
        baseEntitlements,
        new Date("2026-06-15T14:31:00.000Z"),
      ),
    ).toBe(false);
  });

  it("rejects draft or unsent alerts", () => {
    expect(
      canViewAlert(
        {
          state: AlertState.DRAFT,
          createdAt: new Date("2026-06-15T14:00:00.000Z"),
          sentAt: null,
        },
        { ...baseEntitlements, summaryDelayMinutes: 0, alertHistoryDays: null },
      ),
    ).toBe(false);
  });
});

describe("account alert preferences", () => {
  it("gates channels by plan entitlement", () => {
    const form = new FormData();
    form.set("emailEnabled", "on");
    form.set("telegramEnabled", "on");
    form.set("discordEnabled", "on");
    form.set("minimumConfidence", "92");
    form.set("minimumRiskLevel", "HIGH");
    form.append("eventFamilies", "nfp");
    form.append("eventFamilies", "unknown");
    form.append("symbols", "NQ");
    form.append("symbols", "DOGE");

    const parsed = parseAlertPreferenceForm(form, baseEntitlements);

    expect(parsed.emailEnabled).toBe(true);
    expect(parsed.telegramEnabled).toBe(false);
    expect(parsed.discordEnabled).toBe(false);
    expect(parsed.minimumConfidence).toBe(92);
    expect(parsed.minimumRiskLevel).toBe("HIGH");
    expect(parsed.eventFamilies).toEqual(["nfp"]);
    expect(parsed.symbols).toEqual(["NQ"]);
  });

  it("clamps invalid confidence values", () => {
    const form = new FormData();
    form.set("minimumConfidence", "120");
    const parsed = parseAlertPreferenceForm(form, baseEntitlements);
    expect(parsed.minimumConfidence).toBe(100);
  });
});
