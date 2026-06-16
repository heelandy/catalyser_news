import { describe, expect, it } from "vitest";

import {
  AlertChannel,
  SubscriptionState,
  UserRole,
} from "@/generated/prisma/enums";
import {
  canUseAlertChannel,
  isWithinDailyAlertLimit,
  resolveEntitlements,
  resolvePlanCode,
  subscriptionGrantsAccess,
} from "@/lib/plan-access";
import { PLAN_CATALOG } from "@/lib/plan-catalog";

const now = new Date("2026-06-15T14:00:00.000Z");

function subscription(
  planCode: string,
  state: SubscriptionState = SubscriptionState.ACTIVE,
) {
  return {
    planCode,
    state,
    currentPeriodEnd: new Date("2026-07-15T14:00:00.000Z"),
    graceEndsAt: null,
  };
}

describe("plan catalog", () => {
  it("defines distinct free, basic, pro, and elite entitlements", () => {
    expect(PLAN_CATALOG.free.entitlements.summaryDelayMinutes).toBe(30);
    expect(PLAN_CATALOG.basic.entitlements.channels).toEqual([
      AlertChannel.EMAIL,
    ]);
    expect(PLAN_CATALOG.pro.entitlements.preferences).toBe(true);
    expect(PLAN_CATALOG.elite.entitlements.nqPriority).toBe(true);
    expect(PLAN_CATALOG.elite.entitlements.premiumCommunity).toBe(true);
  });

  it("does not grant paid access from a paid role without a valid subscription", () => {
    expect(
      resolvePlanCode({
        role: UserRole.PAID_SUBSCRIBER,
        subscription: null,
        now,
      }),
    ).toBe("free");
  });

  it("resolves active paid subscriptions and admin access", () => {
    expect(
      resolvePlanCode({
        role: UserRole.PAID_SUBSCRIBER,
        subscription: subscription("pro"),
        now,
      }),
    ).toBe("pro");
    expect(
      resolvePlanCode({ role: UserRole.ADMIN, subscription: null, now }),
    ).toBe("elite");
  });

  it("honors a bounded past-due grace period", () => {
    const withinGrace = {
      ...subscription("basic", SubscriptionState.PAST_DUE),
      graceEndsAt: new Date("2026-06-18T14:00:00.000Z"),
    };
    const expiredGrace = {
      ...withinGrace,
      graceEndsAt: new Date("2026-06-14T14:00:00.000Z"),
    };

    expect(subscriptionGrantsAccess(withinGrace, now)).toBe(true);
    expect(subscriptionGrantsAccess(expiredGrace, now)).toBe(false);
  });

  it("enforces channel and daily-alert limits", () => {
    const basic = resolveEntitlements({
      role: UserRole.PAID_SUBSCRIBER,
      subscription: subscription("basic"),
      now,
    });
    expect(canUseAlertChannel(basic, AlertChannel.EMAIL)).toBe(true);
    expect(canUseAlertChannel(basic, AlertChannel.TELEGRAM)).toBe(false);
    expect(isWithinDailyAlertLimit(basic, 4)).toBe(true);
    expect(isWithinDailyAlertLimit(basic, 5)).toBe(false);
  });
});
