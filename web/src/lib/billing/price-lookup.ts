import { BillingInterval, type Plan } from "@/generated/prisma/client";
import { isPlanCode, type PlanCode } from "@/lib/plan-catalog";

export class PriceConfigurationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PriceConfigurationError";
  }
}

export function priceIdFieldForInterval(interval: BillingInterval) {
  switch (interval) {
    case BillingInterval.MONTHLY:
      return "stripeMonthlyPriceId" as const;
    case BillingInterval.QUARTERLY:
      return "stripeQuarterlyPriceId" as const;
    case BillingInterval.ANNUAL:
      return "stripeAnnualPriceId" as const;
  }
}

export function stripePriceIdForPlan(
  plan: Pick<
    Plan,
    | "code"
    | "stripeMonthlyPriceId"
    | "stripeQuarterlyPriceId"
    | "stripeAnnualPriceId"
  >,
  interval: BillingInterval,
) {
  const field = priceIdFieldForInterval(interval);
  const priceId = plan[field];
  if (!priceId) {
    throw new PriceConfigurationError(
      `Stripe ${interval.toLowerCase()} price is not configured for ${plan.code}.`,
    );
  }
  return priceId;
}

export function planCodeFromPriceId(
  priceId: string,
  plans: Array<
    Pick<
      Plan,
      | "code"
      | "stripeMonthlyPriceId"
      | "stripeQuarterlyPriceId"
      | "stripeAnnualPriceId"
    >
  >,
): { planCode: PlanCode; interval: BillingInterval } | null {
  for (const plan of plans) {
    if (!isPlanCode(plan.code)) continue;
    if (plan.stripeMonthlyPriceId === priceId) {
      return { planCode: plan.code, interval: BillingInterval.MONTHLY };
    }
    if (plan.stripeQuarterlyPriceId === priceId) {
      return { planCode: plan.code, interval: BillingInterval.QUARTERLY };
    }
    if (plan.stripeAnnualPriceId === priceId) {
      return { planCode: plan.code, interval: BillingInterval.ANNUAL };
    }
  }

  return null;
}
