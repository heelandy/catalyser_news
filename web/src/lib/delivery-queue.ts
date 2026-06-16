import "server-only";

import { createHash } from "node:crypto";

import {
  AlertState,
  DeliveryStatus,
  UserRole,
  type AlertChannel,
  type Prisma,
  type RiskLevel,
  type SubscriptionState,
} from "@/generated/prisma/client";
import {
  defaultAlertPreference,
  type AlertPreferenceInput,
  type QuietHours,
} from "@/lib/account-preferences";
import { getRequiredDatabase } from "@/lib/db";
import {
  alertMatchesPreference,
  buildDeliveryPayload,
  enabledDeliveryChannels,
  isDailyLimitAvailable,
  nextRetryAtForPlan,
  type VerifiedChannels,
} from "@/lib/delivery-policy";
import {
  resolveEntitlements,
  resolvePlanCode,
  subscriptionGrantsAccess,
} from "@/lib/plan-access";
import { PLAN_CATALOG, type PlanCode } from "@/lib/plan-catalog";

type SubscriptionForDelivery = {
  plan: { code: string; priorityRank: number };
  state: SubscriptionState;
  currentPeriodEnd: Date | null;
  graceEndsAt: Date | null;
};

type PreferenceRecord = {
  emailEnabled: boolean;
  telegramEnabled: boolean;
  discordEnabled: boolean;
  minimumConfidence: number;
  minimumRiskLevel: RiskLevel;
  eventFamilies: unknown;
  symbols: unknown;
  quietHours: unknown;
};

function jsonValue(value: unknown): Prisma.InputJsonValue {
  return JSON.parse(JSON.stringify(value)) as Prisma.InputJsonValue;
}

function hashText(value: string) {
  return createHash("sha256").update(value).digest("hex");
}

function payloadDigest(payload: unknown) {
  return hashText(JSON.stringify(payload));
}

function idempotencyKey(
  alertId: string,
  userId: string,
  channel: AlertChannel,
) {
  return `delivery:${hashText(`${alertId}:${userId}:${channel}`).slice(0, 48)}`;
}

function destinationHash(value: string | null | undefined) {
  return value ? hashText(value).slice(0, 64) : null;
}

function selectSubscription(
  subscriptions: SubscriptionForDelivery[],
  now: Date,
) {
  const granting = subscriptions
    .filter((subscription) =>
      subscriptionGrantsAccess(
        {
          planCode: subscription.plan.code,
          state: subscription.state,
          currentPeriodEnd: subscription.currentPeriodEnd,
          graceEndsAt: subscription.graceEndsAt,
        },
        now,
      ),
    )
    .sort((left, right) => right.plan.priorityRank - left.plan.priorityRank);
  return granting[0] ?? null;
}

function stringArray(value: unknown, fallback: string[]) {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : fallback;
}

function quietHours(value: unknown, fallback: QuietHours) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return fallback;
  }
  const candidate = value as Partial<QuietHours>;
  return {
    enabled: Boolean(candidate.enabled),
    start:
      typeof candidate.start === "string" &&
      /^\d{2}:\d{2}$/.test(candidate.start)
        ? candidate.start
        : fallback.start,
    end:
      typeof candidate.end === "string" && /^\d{2}:\d{2}$/.test(candidate.end)
        ? candidate.end
        : fallback.end,
  };
}

function preferenceFor(
  preference: PreferenceRecord | null | undefined,
  entitlements: ReturnType<typeof resolveEntitlements>,
): AlertPreferenceInput {
  const fallback = defaultAlertPreference(entitlements);
  if (!preference) return fallback;
  return {
    emailEnabled: preference.emailEnabled,
    telegramEnabled: preference.telegramEnabled,
    discordEnabled: preference.discordEnabled,
    minimumConfidence: preference.minimumConfidence,
    minimumRiskLevel: preference.minimumRiskLevel,
    eventFamilies: stringArray(
      preference.eventFamilies,
      fallback.eventFamilies,
    ),
    symbols: stringArray(preference.symbols, fallback.symbols),
    quietHours: quietHours(preference.quietHours, fallback.quietHours),
  };
}

function retainUntil(now: Date) {
  return new Date(now.getTime() + 90 * 24 * 60 * 60 * 1000);
}

function startOfUtcDay(now: Date) {
  return new Date(
    Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()),
  );
}

function planPriority(planCode: PlanCode) {
  return PLAN_CATALOG[planCode].priorityRank;
}

export async function queueApprovedAlert(alertId: string, now = new Date()) {
  const database = getRequiredDatabase();
  const alert = await database.alert.findUnique({
    where: { id: alertId },
    include: {
      marketReaction: {
        select: { eventFamily: true, symbol: true },
      },
    },
  });

  if (!alert || alert.state !== AlertState.APPROVED) {
    return {
      queued: 0,
      skipped: 0,
      duplicateSafe: true,
      reason: "alert_not_approved",
    };
  }

  const users = await database.user.findMany({
    where: {
      deletedAt: null,
      role: UserRole.PAID_SUBSCRIBER,
    },
    include: {
      subscriptions: {
        include: {
          plan: { select: { code: true, priorityRank: true } },
        },
        orderBy: { updatedAt: "desc" },
      },
      alertPreferences: true,
      telegramConnections: {
        where: { disabledAt: null },
        orderBy: { updatedAt: "desc" },
        take: 1,
      },
      discordConnections: {
        where: { disabledAt: null },
        orderBy: { updatedAt: "desc" },
        take: 1,
      },
    },
  });

  const today = startOfUtcDay(now);
  let skipped = 0;
  const attempts: Prisma.AlertDeliveryAttemptCreateManyInput[] = [];

  for (const user of users) {
    const subscription = selectSubscription(user.subscriptions, now);
    const planCode = resolvePlanCode({
      role: user.role,
      subscription: subscription
        ? {
            planCode: subscription.plan.code,
            state: subscription.state,
            currentPeriodEnd: subscription.currentPeriodEnd,
            graceEndsAt: subscription.graceEndsAt,
          }
        : null,
      now,
    });
    const entitlements = resolveEntitlements({
      role: user.role,
      subscription: subscription
        ? {
            planCode: subscription.plan.code,
            state: subscription.state,
            currentPeriodEnd: subscription.currentPeriodEnd,
            graceEndsAt: subscription.graceEndsAt,
          }
        : null,
      now,
    });
    const preference = preferenceFor(user.alertPreferences[0], entitlements);
    const verified: VerifiedChannels = {
      email: Boolean(user.emailVerified),
      telegram: Boolean(user.telegramConnections[0]?.verifiedAt),
      discord: Boolean(user.discordConnections[0]?.verifiedAt),
    };
    const channels = enabledDeliveryChannels({
      entitlements,
      preference,
      verified,
    });

    if (
      !channels.length ||
      !alertMatchesPreference({ alert, preference, now })
    ) {
      skipped += 1;
      continue;
    }

    const deliveryAttemptsToday = await database.alertDeliveryAttempt.findMany({
      where: {
        userId: user.id,
        createdAt: { gte: today },
      },
      select: { alertId: true },
    });
    const alertsQueuedToday = new Set(
      deliveryAttemptsToday.map((attempt) => attempt.alertId),
    ).size;
    if (!isDailyLimitAvailable(entitlements, alertsQueuedToday)) {
      skipped += 1;
      continue;
    }

    const payload = buildDeliveryPayload(alert);
    const digest = payloadDigest(payload);
    for (const channel of channels) {
      const destination =
        channel === "EMAIL"
          ? user.email
          : channel === "TELEGRAM"
            ? user.telegramConnections[0]?.chatId
            : (user.discordConnections[0]?.webhookId ??
              user.discordConnections[0]?.channelId);
      attempts.push({
        alertId: alert.id,
        userId: user.id,
        channel,
        status: DeliveryStatus.QUEUED,
        destinationHash: destinationHash(destination),
        idempotencyKey: idempotencyKey(alert.id, user.id, channel),
        attemptNumber: 1,
        nextRetryAt: nextRetryAtForPlan(entitlements, now),
        payloadDigest: digest,
        rawPayload: jsonValue({
          ...payload,
          planCode,
          priorityRank: planPriority(planCode),
          queuedAt: now.toISOString(),
        }),
        retainUntil: retainUntil(now),
      });
    }
  }

  if (!attempts.length) {
    return {
      queued: 0,
      skipped,
      duplicateSafe: true,
      reason: "no_eligible_subscribers",
    };
  }

  const result = await database.alertDeliveryAttempt.createMany({
    data: attempts,
    skipDuplicates: true,
  });

  return {
    queued: result.count,
    skipped,
    duplicateSafe: true,
    reason: "queued",
  };
}
