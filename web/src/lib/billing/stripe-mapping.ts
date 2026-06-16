import type Stripe from "stripe";

import {
  InvoiceStatus,
  PaymentStatus,
  SubscriptionState,
} from "@/generated/prisma/enums";

export const PAYMENT_FAILURE_GRACE_DAYS = 3;

export function dateFromStripeTimestamp(value: number | null | undefined) {
  return value ? new Date(value * 1000) : null;
}

export function stripeSubscriptionStatusToState(
  status: Stripe.Subscription.Status | "incomplete_expired",
) {
  switch (status) {
    case "active":
      return SubscriptionState.ACTIVE;
    case "trialing":
      return SubscriptionState.TRIALING;
    case "past_due":
      return SubscriptionState.PAST_DUE;
    case "canceled":
      return SubscriptionState.CANCELED;
    case "unpaid":
      return SubscriptionState.UNPAID;
    case "paused":
      return SubscriptionState.PAUSED;
    case "incomplete_expired":
      return SubscriptionState.EXPIRED;
    case "incomplete":
    default:
      return SubscriptionState.INCOMPLETE;
  }
}

export function stripeInvoiceStatusToStatus(
  status: Stripe.Invoice.Status | null,
) {
  switch (status) {
    case "paid":
      return InvoiceStatus.PAID;
    case "void":
      return InvoiceStatus.VOID;
    case "uncollectible":
      return InvoiceStatus.UNCOLLECTIBLE;
    case "open":
      return InvoiceStatus.OPEN;
    case "draft":
    default:
      return InvoiceStatus.DRAFT;
  }
}

export function paymentStatusForInvoiceEvent(eventType: string) {
  if (
    eventType === "invoice.paid" ||
    eventType === "invoice.payment_succeeded"
  ) {
    return PaymentStatus.SUCCEEDED;
  }
  if (eventType === "invoice.payment_failed") {
    return PaymentStatus.FAILED;
  }
  return PaymentStatus.PROCESSING;
}

export function graceEndFromEventTimestamp(eventCreated: number) {
  return new Date(
    (eventCreated + PAYMENT_FAILURE_GRACE_DAYS * 24 * 60 * 60) * 1000,
  );
}

export function stringId(value: string | { id: string } | null | undefined) {
  if (!value) return null;
  return typeof value === "string" ? value : value.id;
}

export function firstSubscriptionPriceId(subscription: Stripe.Subscription) {
  return subscription.items.data[0]?.price.id ?? null;
}
