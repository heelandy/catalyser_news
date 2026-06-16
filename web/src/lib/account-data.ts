import "server-only";

import {
  AlertChannel,
  AlertState,
  SubscriptionState,
  UserRole,
  type UserRole as UserRoleValue,
} from "@/generated/prisma/enums";
import { filterVisibleAlerts } from "@/lib/account-access";
import {
  defaultAlertPreference,
  type AlertPreferenceInput,
  type QuietHours,
} from "@/lib/account-preferences";
import { getRequiredDatabase } from "@/lib/db";
import { isBillingConfigured } from "@/lib/billing/stripe-config";
import { maskDiscordWebhookId } from "@/lib/discord-connection";
import {
  resolveEntitlements,
  resolvePlanCode,
  subscriptionGrantsAccess,
} from "@/lib/plan-access";
import { PLAN_CATALOG, type PlanCode } from "@/lib/plan-catalog";
import { getServerEnv } from "@/lib/env";

type SubscriptionWithPlan = Awaited<
  ReturnType<typeof getAccountSubscriptions>
>[number];

async function getAccountSubscriptions(userId: string) {
  return getRequiredDatabase().subscription.findMany({
    where: { userId },
    include: {
      plan: {
        select: {
          code: true,
          name: true,
          priorityRank: true,
        },
      },
    },
    orderBy: [{ updatedAt: "desc" }],
  });
}

function selectCurrentSubscription(
  subscriptions: SubscriptionWithPlan[],
  role: UserRoleValue,
) {
  if (role === UserRole.ADMIN) return null;

  const granting = subscriptions
    .filter((subscription) =>
      subscriptionGrantsAccess({
        planCode: subscription.plan.code,
        state: subscription.state,
        currentPeriodEnd: subscription.currentPeriodEnd,
        graceEndsAt: subscription.graceEndsAt,
      }),
    )
    .sort((left, right) => right.plan.priorityRank - left.plan.priorityRank);

  return granting[0] ?? subscriptions[0] ?? null;
}

function preferenceFromRecord(
  preference: {
    emailEnabled: boolean;
    telegramEnabled: boolean;
    discordEnabled: boolean;
    minimumConfidence: number;
    minimumRiskLevel: AlertPreferenceInput["minimumRiskLevel"];
    eventFamilies: unknown;
    symbols: unknown;
    quietHours: unknown;
  } | null,
  fallback: AlertPreferenceInput,
): AlertPreferenceInput {
  if (!preference) return fallback;
  const quietHours =
    preference.quietHours &&
    typeof preference.quietHours === "object" &&
    !Array.isArray(preference.quietHours)
      ? (preference.quietHours as QuietHours)
      : fallback.quietHours;

  return {
    emailEnabled: preference.emailEnabled,
    telegramEnabled: preference.telegramEnabled,
    discordEnabled: preference.discordEnabled,
    minimumConfidence: preference.minimumConfidence,
    minimumRiskLevel: preference.minimumRiskLevel,
    eventFamilies: Array.isArray(preference.eventFamilies)
      ? preference.eventFamilies.filter(
          (value): value is string => typeof value === "string",
        )
      : fallback.eventFamilies,
    symbols: Array.isArray(preference.symbols)
      ? preference.symbols.filter(
          (value): value is string => typeof value === "string",
        )
      : fallback.symbols,
    quietHours,
  };
}

export function periodLabel(subscription: SubscriptionWithPlan | null) {
  if (!subscription) return "No active billing period";
  if (subscription.trialEndsAt) return "Trial ends";
  if (subscription.graceEndsAt) return "Payment grace ends";
  if (subscription.currentPeriodEnd && subscription.cancelAtPeriodEnd) {
    return "Access ends";
  }
  if (subscription.currentPeriodEnd) return "Renews";
  return "Billing period";
}

export function formatDate(value: Date | null) {
  if (!value) return "Not set";
  return new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(value);
}

export function formatCurrency(cents: number, currency = "usd") {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: currency.toUpperCase(),
  }).format(cents / 100);
}

export async function loadAccountSnapshot(user: {
  id: string;
  role: UserRoleValue;
}) {
  const database = getRequiredDatabase();
  const subscriptions = await getAccountSubscriptions(user.id);
  const currentSubscription = selectCurrentSubscription(
    subscriptions,
    user.role,
  );
  const planCode = resolvePlanCode({
    role: user.role,
    subscription: currentSubscription
      ? {
          planCode: currentSubscription.plan.code,
          state: currentSubscription.state,
          currentPeriodEnd: currentSubscription.currentPeriodEnd,
          graceEndsAt: currentSubscription.graceEndsAt,
        }
      : null,
  });
  const entitlements = resolveEntitlements({
    role: user.role,
    subscription: currentSubscription
      ? {
          planCode: currentSubscription.plan.code,
          state: currentSubscription.state,
          currentPeriodEnd: currentSubscription.currentPeriodEnd,
          graceEndsAt: currentSubscription.graceEndsAt,
        }
      : null,
  });

  const [preference, invoices, deliveryAttempts, telegram, discord, alerts] =
    await Promise.all([
      database.alertPreference.findUnique({ where: { userId: user.id } }),
      database.invoice.findMany({
        where: { userId: user.id },
        orderBy: { createdAt: "desc" },
        take: 8,
      }),
      database.alertDeliveryAttempt.findMany({
        where: { userId: user.id },
        include: {
          alert: {
            select: {
              headline: true,
              bias: true,
              confidence: true,
              createdAt: true,
              sentAt: true,
            },
          },
        },
        orderBy: { createdAt: "desc" },
        take: 8,
      }),
      database.telegramConnection.findFirst({
        where: { userId: user.id, disabledAt: null },
        orderBy: { updatedAt: "desc" },
      }),
      database.discordConnection.findFirst({
        where: { userId: user.id, disabledAt: null },
        orderBy: { updatedAt: "desc" },
      }),
      database.alert.findMany({
        where: { state: AlertState.SENT },
        orderBy: { createdAt: "desc" },
        take: 30,
      }),
    ]);

  return {
    planCode,
    plan: PLAN_CATALOG[planCode as PlanCode],
    entitlements,
    currentSubscription,
    billingConfigured: isBillingConfigured(),
    preference: preferenceFromRecord(
      preference,
      defaultAlertPreference(entitlements),
    ),
    invoices,
    visibleAlerts: filterVisibleAlerts(alerts, entitlements).slice(0, 8),
    deliveryAttempts,
    channels: {
      email: {
        available: entitlements.channels.includes(AlertChannel.EMAIL),
        enabled:
          preference?.emailEnabled ??
          entitlements.channels.includes(AlertChannel.EMAIL),
        verified: true,
      },
      telegram: {
        available: entitlements.channels.includes(AlertChannel.TELEGRAM),
        enabled: preference?.telegramEnabled ?? false,
        verified: Boolean(telegram?.verifiedAt),
        pending: Boolean(
          telegram?.verificationCodeHash && !telegram.verifiedAt,
        ),
        botUsername: getServerEnv().TELEGRAM_BOT_USERNAME ?? null,
        chatId: telegram?.chatId ?? null,
        verifiedAt: telegram?.verifiedAt ?? null,
      },
      discord: {
        available: entitlements.channels.includes(AlertChannel.DISCORD),
        enabled: preference?.discordEnabled ?? false,
        verified: Boolean(discord?.verifiedAt),
        webhookId: maskDiscordWebhookId(discord?.webhookId),
        verifiedAt: discord?.verifiedAt ?? null,
      },
    },
    status: currentSubscription?.state ?? SubscriptionState.INCOMPLETE,
  };
}
