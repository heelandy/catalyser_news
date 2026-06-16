import "server-only";

import {
  AlertState,
  DeliveryStatus,
  InvoiceStatus,
  PaymentStatus,
  SubscriptionState,
  type SubscriptionState as SubscriptionStateValue,
} from "@/generated/prisma/enums";
import { getRequiredDatabase } from "@/lib/db";

export const SUBSCRIPTION_FILTERS = [
  SubscriptionState.ACTIVE,
  SubscriptionState.TRIALING,
  SubscriptionState.CANCELED,
  SubscriptionState.PAST_DUE,
  SubscriptionState.UNPAID,
] as const;

export function parseSubscriptionStateFilter(value: unknown) {
  if (typeof value !== "string") return null;
  const normalized = value.toUpperCase();
  return SUBSCRIPTION_FILTERS.find((state) => state === normalized) ?? null;
}

export async function loadAdminSnapshot(options?: {
  subscriptionState?: SubscriptionStateValue | null;
}) {
  const database = getRequiredDatabase();
  const since24Hours = new Date(Date.now() - 24 * 60 * 60 * 1000);
  const subscriptionState = options?.subscriptionState ?? null;
  const subscriberWhere = subscriptionState
    ? { subscriptions: { some: { state: subscriptionState } } }
    : {};

  const [
    totalUsers,
    newUsers,
    activeSubscriptions,
    trialingSubscriptions,
    canceledSubscriptions,
    pastDueSubscriptions,
    unpaidSubscriptions,
    pendingAlerts,
    failedPayments,
    failedDeliveries,
    paidInvoiceRevenue,
    newsEvents,
    marketReactions,
    reviewQueue,
    alertHistory,
    deliveryHistory,
    subscribers,
    failedPaymentRows,
    auditLogs,
  ] = await Promise.all([
    database.user.count(),
    database.user.count({ where: { createdAt: { gte: since24Hours } } }),
    database.subscription.count({ where: { state: SubscriptionState.ACTIVE } }),
    database.subscription.count({
      where: { state: SubscriptionState.TRIALING },
    }),
    database.subscription.count({
      where: { state: SubscriptionState.CANCELED },
    }),
    database.subscription.count({
      where: { state: SubscriptionState.PAST_DUE },
    }),
    database.subscription.count({ where: { state: SubscriptionState.UNPAID } }),
    database.alert.count({
      where: { state: { in: [AlertState.DRAFT, AlertState.PENDING] } },
    }),
    database.payment.count({ where: { status: PaymentStatus.FAILED } }),
    database.alertDeliveryAttempt.count({
      where: {
        status: { in: [DeliveryStatus.FAILED, DeliveryStatus.DEAD_LETTER] },
      },
    }),
    database.invoice.aggregate({
      where: { status: InvoiceStatus.PAID },
      _sum: { totalCents: true },
    }),
    database.newsEvent.findMany({
      orderBy: [{ occurredAt: "desc" }, { fetchedAt: "desc" }],
      take: 8,
    }),
    database.marketReaction.findMany({
      include: {
        newsEvent: {
          select: { headline: true, source: true, publisher: true },
        },
      },
      orderBy: { createdAt: "desc" },
      take: 8,
    }),
    database.alert.findMany({
      where: { state: { in: [AlertState.DRAFT, AlertState.PENDING] } },
      include: {
        marketReaction: {
          include: {
            newsEvent: {
              select: { headline: true, source: true, publisher: true },
            },
          },
        },
      },
      orderBy: { createdAt: "desc" },
      take: 12,
    }),
    database.alert.findMany({
      include: {
        approvedBy: { select: { email: true } },
        rejectedBy: { select: { email: true } },
      },
      orderBy: { updatedAt: "desc" },
      take: 12,
    }),
    database.alertDeliveryAttempt.findMany({
      include: {
        alert: { select: { headline: true, state: true } },
        user: { select: { email: true } },
      },
      orderBy: { createdAt: "desc" },
      take: 12,
    }),
    database.user.findMany({
      where: subscriberWhere,
      include: {
        subscriptions: {
          include: {
            plan: { select: { code: true, name: true } },
          },
          orderBy: { updatedAt: "desc" },
          take: 2,
        },
        invoices: {
          orderBy: { createdAt: "desc" },
          take: 1,
        },
        payments: {
          orderBy: { createdAt: "desc" },
          take: 1,
        },
      },
      orderBy: { createdAt: "desc" },
      take: 12,
    }),
    database.payment.findMany({
      where: { status: PaymentStatus.FAILED },
      include: {
        user: { select: { email: true } },
      },
      orderBy: { createdAt: "desc" },
      take: 8,
    }),
    database.adminAuditLog.findMany({
      include: {
        actorUser: { select: { email: true } },
        targetUser: { select: { email: true } },
      },
      orderBy: { createdAt: "desc" },
      take: 10,
    }),
  ]);

  return {
    metrics: {
      totalUsers,
      newUsers,
      pendingAlerts,
      failedPayments,
      failedDeliveries,
      paidRevenueCents: paidInvoiceRevenue._sum.totalCents ?? 0,
      subscriptions: {
        active: activeSubscriptions,
        trialing: trialingSubscriptions,
        canceled: canceledSubscriptions,
        pastDue: pastDueSubscriptions,
        unpaid: unpaidSubscriptions,
      },
    },
    subscriptionState,
    newsEvents,
    marketReactions,
    reviewQueue,
    alertHistory,
    deliveryHistory,
    subscribers,
    failedPaymentRows,
    auditLogs,
  };
}
