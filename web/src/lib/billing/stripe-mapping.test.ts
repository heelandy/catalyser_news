import { describe, expect, it } from "vitest";

import {
  BillingInterval,
  InvoiceStatus,
  PaymentStatus,
  SubscriptionState,
} from "@/generated/prisma/enums";
import {
  priceIdFieldForInterval,
  planCodeFromPriceId,
} from "@/lib/billing/price-lookup";
import {
  graceEndFromEventTimestamp,
  paymentStatusForInvoiceEvent,
  stripeInvoiceStatusToStatus,
  stripeSubscriptionStatusToState,
} from "@/lib/billing/stripe-mapping";

describe("Stripe billing mapping", () => {
  it("maps Stripe subscription states to local states", () => {
    expect(stripeSubscriptionStatusToState("active")).toBe(
      SubscriptionState.ACTIVE,
    );
    expect(stripeSubscriptionStatusToState("trialing")).toBe(
      SubscriptionState.TRIALING,
    );
    expect(stripeSubscriptionStatusToState("past_due")).toBe(
      SubscriptionState.PAST_DUE,
    );
    expect(stripeSubscriptionStatusToState("incomplete_expired")).toBe(
      SubscriptionState.EXPIRED,
    );
  });

  it("maps invoice and payment event states", () => {
    expect(stripeInvoiceStatusToStatus("paid")).toBe(InvoiceStatus.PAID);
    expect(stripeInvoiceStatusToStatus("uncollectible")).toBe(
      InvoiceStatus.UNCOLLECTIBLE,
    );
    expect(paymentStatusForInvoiceEvent("invoice.paid")).toBe(
      PaymentStatus.SUCCEEDED,
    );
    expect(paymentStatusForInvoiceEvent("invoice.payment_failed")).toBe(
      PaymentStatus.FAILED,
    );
  });

  it("resolves configured price IDs back to local plans", () => {
    const plans = [
      {
        code: "basic",
        stripeMonthlyPriceId: "price_basic_m",
        stripeQuarterlyPriceId: "price_basic_q",
        stripeAnnualPriceId: "price_basic_y",
      },
    ];

    expect(planCodeFromPriceId("price_basic_q", plans)).toEqual({
      planCode: "basic",
      interval: BillingInterval.QUARTERLY,
    });
    expect(planCodeFromPriceId("missing", plans)).toBeNull();
  });

  it("selects the correct plan price field for each interval", () => {
    expect(priceIdFieldForInterval(BillingInterval.MONTHLY)).toBe(
      "stripeMonthlyPriceId",
    );
    expect(priceIdFieldForInterval(BillingInterval.QUARTERLY)).toBe(
      "stripeQuarterlyPriceId",
    );
    expect(priceIdFieldForInterval(BillingInterval.ANNUAL)).toBe(
      "stripeAnnualPriceId",
    );
  });

  it("creates a bounded grace window from failed-payment events", () => {
    expect(graceEndFromEventTimestamp(1_781_532_000).toISOString()).toBe(
      "2026-06-18T14:00:00.000Z",
    );
  });
});
