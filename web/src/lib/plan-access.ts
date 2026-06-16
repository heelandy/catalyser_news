import {
  AlertChannel,
  SubscriptionState,
  UserRole,
} from "@/generated/prisma/enums";
import {
  isPlanCode,
  PLAN_CATALOG,
  type PlanCode,
  type PlanEntitlements,
} from "@/lib/plan-catalog";

export type SubscriptionAccess = {
  planCode: string;
  state: SubscriptionState;
  currentPeriodEnd: Date | null;
  graceEndsAt: Date | null;
};

export function subscriptionGrantsAccess(
  subscription: SubscriptionAccess,
  now = new Date(),
) {
  if (
    subscription.state === SubscriptionState.ACTIVE ||
    subscription.state === SubscriptionState.TRIALING
  ) {
    return (
      !subscription.currentPeriodEnd || subscription.currentPeriodEnd > now
    );
  }

  return (
    subscription.state === SubscriptionState.PAST_DUE &&
    Boolean(subscription.graceEndsAt && subscription.graceEndsAt > now)
  );
}

export function resolvePlanCode({
  role,
  subscription,
  now = new Date(),
}: {
  role: UserRole;
  subscription: SubscriptionAccess | null;
  now?: Date;
}): PlanCode {
  if (role === UserRole.ADMIN) return "elite";
  if (
    role === UserRole.PAID_SUBSCRIBER &&
    subscription &&
    isPlanCode(subscription.planCode) &&
    subscriptionGrantsAccess(subscription, now)
  ) {
    return subscription.planCode;
  }
  return "free";
}

export function resolveEntitlements(input: {
  role: UserRole;
  subscription: SubscriptionAccess | null;
  now?: Date;
}): PlanEntitlements {
  return PLAN_CATALOG[resolvePlanCode(input)].entitlements;
}

export function canUseAlertChannel(
  entitlements: PlanEntitlements,
  channel: AlertChannel,
) {
  return entitlements.channels.includes(channel);
}

export function isWithinDailyAlertLimit(
  entitlements: PlanEntitlements,
  alertsSentToday: number,
) {
  return (
    entitlements.dailyAlertLimit === null ||
    alertsSentToday < entitlements.dailyAlertLimit
  );
}
