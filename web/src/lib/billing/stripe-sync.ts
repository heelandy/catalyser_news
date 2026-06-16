import "server-only";

import type Stripe from "stripe";

import {
  BillingInterval,
  PaymentStatus,
  SubscriptionState,
  UserRole,
  type Prisma,
} from "@/generated/prisma/client";
import { getRequiredDatabase } from "@/lib/db";
import { isPlanCode } from "@/lib/plan-catalog";
import { planCodeFromPriceId } from "@/lib/billing/price-lookup";
import {
  dateFromStripeTimestamp,
  firstSubscriptionPriceId,
  graceEndFromEventTimestamp,
  paymentStatusForInvoiceEvent,
  stringId,
  stripeInvoiceStatusToStatus,
  stripeSubscriptionStatusToState,
} from "@/lib/billing/stripe-mapping";
import { subscriptionGrantsAccess } from "@/lib/plan-access";

type ProcessingResult = {
  status: "processed" | "duplicate" | "ignored";
  message?: string;
};

type StripeSubscriptionItemPeriods = {
  items?: {
    data?: Array<{
      current_period_start?: number;
      current_period_end?: number;
    }>;
  };
};

function stripeSubscriptionPeriods(subscription: Stripe.Subscription) {
  const firstItem = (subscription as StripeSubscriptionItemPeriods).items
    ?.data?.[0];
  return {
    currentPeriodStart: dateFromStripeTimestamp(
      firstItem?.current_period_start,
    ),
    currentPeriodEnd: dateFromStripeTimestamp(firstItem?.current_period_end),
  };
}

function jsonPayload(value: unknown): Prisma.InputJsonValue {
  return JSON.parse(JSON.stringify(value)) as Prisma.InputJsonValue;
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

function intervalFromMetadata(value: string | undefined) {
  if (value === BillingInterval.QUARTERLY) return BillingInterval.QUARTERLY;
  if (value === BillingInterval.ANNUAL) return BillingInterval.ANNUAL;
  return BillingInterval.MONTHLY;
}

async function refreshUserRole(userId: string) {
  const database = getRequiredDatabase();
  const user = await database.user.findUnique({ where: { id: userId } });
  if (!user || user.role === UserRole.ADMIN) return;

  const subscriptions = await database.subscription.findMany({
    where: { userId },
    include: { plan: { select: { code: true } } },
  });
  const now = new Date();
  const hasPaidAccess = subscriptions.some((subscription) =>
    subscriptionGrantsAccess(
      {
        planCode: subscription.plan.code,
        state: subscription.state,
        currentPeriodEnd: subscription.currentPeriodEnd,
        graceEndsAt: subscription.graceEndsAt,
      },
      now,
    ),
  );

  await database.user.update({
    where: { id: userId },
    data: {
      role: hasPaidAccess ? UserRole.PAID_SUBSCRIBER : UserRole.FREE_USER,
    },
  });
}

async function findUserIdForCustomer(customerId: string | null) {
  if (!customerId) return null;
  const database = getRequiredDatabase();
  const subscription = await database.subscription.findFirst({
    where: { stripeCustomerId: customerId },
    select: { userId: true },
  });
  return subscription?.userId ?? null;
}

async function handleSubscription(subscription: Stripe.Subscription) {
  const database = getRequiredDatabase();
  const customerId = stringId(subscription.customer);
  const plans = await database.plan.findMany({
    select: {
      id: true,
      code: true,
      stripeMonthlyPriceId: true,
      stripeQuarterlyPriceId: true,
      stripeAnnualPriceId: true,
    },
  });
  const priceId = firstSubscriptionPriceId(subscription);
  const mappedPrice = priceId ? planCodeFromPriceId(priceId, plans) : null;
  const metadataPlan = subscription.metadata?.planCode;
  const planCode =
    mappedPrice?.planCode ??
    (metadataPlan && isPlanCode(metadataPlan) ? metadataPlan : null);
  const plan = planCode
    ? plans.find((candidate) => candidate.code === planCode)
    : null;
  const existing = await database.subscription.findUnique({
    where: { stripeSubscriptionId: subscription.id },
    select: { userId: true },
  });
  const userId =
    subscription.metadata?.userId ??
    existing?.userId ??
    (await findUserIdForCustomer(customerId));

  if (!userId || !plan) {
    return {
      status: "ignored" as const,
      message: "Subscription missing user or plan mapping.",
    };
  }

  const periods = stripeSubscriptionPeriods(subscription);
  const status = stripeSubscriptionStatusToState(subscription.status);
  const isPaymentFailure =
    status === SubscriptionState.PAST_DUE ||
    status === SubscriptionState.UNPAID;

  await database.subscription.upsert({
    where: { stripeSubscriptionId: subscription.id },
    update: {
      planId: plan.id,
      state: status,
      billingInterval:
        mappedPrice?.interval ??
        intervalFromMetadata(subscription.metadata?.billingInterval),
      stripeCustomerId: customerId,
      stripePriceId: priceId,
      currentPeriodStart: periods.currentPeriodStart,
      currentPeriodEnd: periods.currentPeriodEnd,
      trialEndsAt: dateFromStripeTimestamp(subscription.trial_end),
      cancelAtPeriodEnd: subscription.cancel_at_period_end,
      canceledAt: dateFromStripeTimestamp(subscription.canceled_at),
      graceEndsAt: isPaymentFailure ? null : null,
      metadata: jsonPayload(subscription.metadata ?? {}),
    },
    create: {
      userId,
      planId: plan.id,
      state: status,
      billingInterval:
        mappedPrice?.interval ??
        intervalFromMetadata(subscription.metadata?.billingInterval),
      stripeCustomerId: customerId,
      stripeSubscriptionId: subscription.id,
      stripePriceId: priceId,
      currentPeriodStart: periods.currentPeriodStart,
      currentPeriodEnd: periods.currentPeriodEnd,
      trialEndsAt: dateFromStripeTimestamp(subscription.trial_end),
      cancelAtPeriodEnd: subscription.cancel_at_period_end,
      canceledAt: dateFromStripeTimestamp(subscription.canceled_at),
      metadata: jsonPayload(subscription.metadata ?? {}),
    },
  });

  await refreshUserRole(userId);
  return { status: "processed" as const };
}

async function findLocalSubscription(
  stripeSubscriptionId: string | null,
  stripeCustomerId: string | null,
) {
  const database = getRequiredDatabase();
  if (stripeSubscriptionId) {
    const subscription = await database.subscription.findUnique({
      where: { stripeSubscriptionId },
      include: { plan: { select: { code: true } } },
    });
    if (subscription) return subscription;
  }
  if (stripeCustomerId) {
    return database.subscription.findFirst({
      where: { stripeCustomerId },
      orderBy: { updatedAt: "desc" },
      include: { plan: { select: { code: true } } },
    });
  }
  return null;
}

async function handleInvoice(event: Stripe.Event) {
  const database = getRequiredDatabase();
  const invoice = event.data.object as Stripe.Invoice;
  const customerId = stringId(invoice.customer);
  const stripeSubscriptionId = stringId(
    (invoice as { subscription?: string | { id: string } }).subscription,
  );
  const paymentIntentId = stringId(
    (invoice as { payment_intent?: string | { id: string } }).payment_intent,
  );
  const chargeId = stringId(
    (invoice as { charge?: string | { id: string } }).charge,
  );
  const localSubscription = await findLocalSubscription(
    stripeSubscriptionId,
    customerId,
  );
  const userId =
    localSubscription?.userId ??
    invoice.metadata?.userId ??
    (await findUserIdForCustomer(customerId));

  if (!userId) {
    return {
      status: "ignored" as const,
      message: "Invoice missing user mapping.",
    };
  }

  const invoiceRecord = await database.invoice.upsert({
    where: { stripeInvoiceId: invoice.id },
    update: {
      subscriptionId: localSubscription?.id,
      status: stripeInvoiceStatusToStatus(invoice.status),
      number: invoice.number,
      rawEventId: event.id,
      currency: invoice.currency,
      subtotalCents: invoice.subtotal ?? 0,
      totalCents: invoice.total ?? 0,
      amountDueCents: invoice.amount_due ?? 0,
      amountPaidCents: invoice.amount_paid ?? 0,
      hostedUrl: invoice.hosted_invoice_url,
      pdfUrl: invoice.invoice_pdf,
      paidAt:
        invoice.status === "paid"
          ? dateFromStripeTimestamp(event.created)
          : null,
      rawPayload: jsonPayload(invoice),
    },
    create: {
      userId,
      subscriptionId: localSubscription?.id,
      status: stripeInvoiceStatusToStatus(invoice.status),
      stripeInvoiceId: invoice.id,
      number: invoice.number,
      rawEventId: event.id,
      currency: invoice.currency,
      subtotalCents: invoice.subtotal ?? 0,
      totalCents: invoice.total ?? 0,
      amountDueCents: invoice.amount_due ?? 0,
      amountPaidCents: invoice.amount_paid ?? 0,
      hostedUrl: invoice.hosted_invoice_url,
      pdfUrl: invoice.invoice_pdf,
      paidAt:
        invoice.status === "paid"
          ? dateFromStripeTimestamp(event.created)
          : null,
      rawPayload: jsonPayload(invoice),
    },
  });

  const paymentStatus = paymentStatusForInvoiceEvent(event.type);
  if (paymentStatus !== PaymentStatus.PROCESSING || invoice.amount_due > 0) {
    await database.payment.upsert({
      where: { rawEventId: event.id },
      update: {
        status: paymentStatus,
        amountCents:
          invoice.amount_paid || invoice.amount_due || invoice.total || 0,
        currency: invoice.currency,
        stripePaymentIntentId: paymentIntentId,
        stripeChargeId: chargeId,
        invoiceId: invoiceRecord.id,
        subscriptionId: localSubscription?.id,
        paidAt:
          paymentStatus === PaymentStatus.SUCCEEDED
            ? dateFromStripeTimestamp(event.created)
            : null,
        failedAt:
          paymentStatus === PaymentStatus.FAILED
            ? dateFromStripeTimestamp(event.created)
            : null,
        rawPayload: jsonPayload(invoice),
      },
      create: {
        userId,
        subscriptionId: localSubscription?.id,
        invoiceId: invoiceRecord.id,
        status: paymentStatus,
        amountCents:
          invoice.amount_paid || invoice.amount_due || invoice.total || 0,
        currency: invoice.currency,
        stripePaymentIntentId: paymentIntentId,
        stripeChargeId: chargeId,
        rawEventId: event.id,
        paidAt:
          paymentStatus === PaymentStatus.SUCCEEDED
            ? dateFromStripeTimestamp(event.created)
            : null,
        failedAt:
          paymentStatus === PaymentStatus.FAILED
            ? dateFromStripeTimestamp(event.created)
            : null,
        rawPayload: jsonPayload(invoice),
      },
    });
  }

  if (localSubscription && paymentStatus === PaymentStatus.FAILED) {
    await database.subscription.update({
      where: { id: localSubscription.id },
      data: {
        state: SubscriptionState.PAST_DUE,
        graceEndsAt: graceEndFromEventTimestamp(event.created),
      },
    });
  }

  if (localSubscription && paymentStatus === PaymentStatus.SUCCEEDED) {
    await database.subscription.update({
      where: { id: localSubscription.id },
      data: {
        state: SubscriptionState.ACTIVE,
        graceEndsAt: null,
      },
    });
  }

  await refreshUserRole(userId);
  return { status: "processed" as const };
}

async function handleCharge(event: Stripe.Event) {
  const database = getRequiredDatabase();
  const charge = event.data.object as Stripe.Charge;
  const paymentIntentId = stringId(charge.payment_intent);
  const fullRefund =
    event.type === "charge.refunded" && charge.amount_refunded >= charge.amount;
  const dispute = event.type === "charge.dispute.created";
  if (!fullRefund && !dispute) return { status: "ignored" as const };

  const payment = await database.payment.findFirst({
    where: {
      OR: [
        { stripeChargeId: charge.id },
        ...(paymentIntentId
          ? [{ stripePaymentIntentId: paymentIntentId }]
          : []),
      ],
    },
    include: { subscription: true },
  });

  if (!payment?.subscription) {
    return {
      status: "ignored" as const,
      message: "Charge missing local payment mapping.",
    };
  }

  await database.payment.update({
    where: { id: payment.id },
    data: {
      status: fullRefund ? PaymentStatus.REFUNDED : PaymentStatus.FAILED,
      rawPayload: jsonPayload(charge),
    },
  });
  await database.subscription.update({
    where: { id: payment.subscription.id },
    data: {
      state: SubscriptionState.CANCELED,
      canceledAt: dateFromStripeTimestamp(event.created),
      currentPeriodEnd: dateFromStripeTimestamp(event.created),
      graceEndsAt: null,
    },
  });
  await refreshUserRole(payment.userId);
  return { status: "processed" as const };
}

async function dispatchStripeEvent(
  event: Stripe.Event,
): Promise<ProcessingResult> {
  switch (event.type) {
    case "checkout.session.completed": {
      const session = event.data.object as Stripe.Checkout.Session;
      const subscriptionId = stringId(session.subscription);
      if (!subscriptionId)
        return { status: "ignored", message: "Checkout missing subscription." };
      return {
        status: "processed",
        message: "Checkout completed; subscription webhooks finalize access.",
      };
    }
    case "customer.subscription.created":
    case "customer.subscription.updated":
    case "customer.subscription.deleted":
    case "customer.subscription.paused":
    case "customer.subscription.resumed":
      return handleSubscription(event.data.object as Stripe.Subscription);
    case "invoice.paid":
    case "invoice.payment_succeeded":
    case "invoice.payment_failed":
    case "invoice.updated":
      return handleInvoice(event);
    case "charge.refunded":
    case "charge.dispute.created":
      return handleCharge(event);
    default:
      return {
        status: "ignored",
        message: `Unhandled event type ${event.type}.`,
      };
  }
}

export async function processStripeEvent(
  event: Stripe.Event,
): Promise<ProcessingResult> {
  const database = getRequiredDatabase();
  const existing = await database.stripeWebhookEvent.findUnique({
    where: { eventId: event.id },
  });
  if (existing) return { status: "duplicate" };

  await database.stripeWebhookEvent.create({
    data: {
      eventId: event.id,
      eventType: event.type,
      status: "processing",
      rawPayload: jsonPayload(event),
    },
  });

  try {
    const result = await dispatchStripeEvent(event);
    await database.stripeWebhookEvent.update({
      where: { eventId: event.id },
      data: {
        status: result.status,
        errorMessage: result.message,
        processedAt: new Date(),
      },
    });
    return result;
  } catch (error) {
    await database.stripeWebhookEvent.update({
      where: { eventId: event.id },
      data: {
        status: "failed",
        errorMessage: errorMessage(error),
      },
    });
    throw error;
  }
}
