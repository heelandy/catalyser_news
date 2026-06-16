import { NextResponse } from "next/server";
import { z } from "zod";

import { auth } from "@/auth";
import { BillingInterval, PlanStatus } from "@/generated/prisma/client";
import {
  BillingConfigurationError,
  requireStripeClient,
} from "@/lib/billing/stripe-config";
import {
  PriceConfigurationError,
  stripePriceIdForPlan,
} from "@/lib/billing/price-lookup";
import { authorizeRoute } from "@/lib/authz";
import { getRequiredDatabase } from "@/lib/db";
import { getServerEnv } from "@/lib/env";
import { rejectCrossOriginRequest } from "@/lib/request-security";

const checkoutRequestSchema = z.object({
  planCode: z.enum(["basic", "pro", "elite"]),
  interval: z.enum(BillingInterval),
});

function errorResponse(error: unknown) {
  if (
    error instanceof BillingConfigurationError ||
    error instanceof PriceConfigurationError
  ) {
    return NextResponse.json({ error: error.message }, { status: 503 });
  }
  if (error instanceof z.ZodError) {
    return NextResponse.json(
      { error: "Invalid checkout request." },
      { status: 400 },
    );
  }
  throw error;
}

export async function POST(request: Request) {
  try {
    const env = getServerEnv();
    const crossOrigin = rejectCrossOriginRequest(request, env.APP_BASE_URL);
    if (crossOrigin) return crossOrigin;

    const session = await auth();
    const decision = authorizeRoute(session);
    if (decision === "unauthenticated") {
      return NextResponse.json(
        { error: "Sign in before checkout." },
        { status: 401 },
      );
    }

    const input = checkoutRequestSchema.parse(await request.json());
    const database = getRequiredDatabase();
    const plan = await database.plan.findUnique({
      where: { code: input.planCode },
    });
    if (!plan || plan.status !== PlanStatus.ACTIVE) {
      return NextResponse.json(
        { error: "Plan is not available." },
        { status: 404 },
      );
    }

    const stripe = requireStripeClient();
    const priceId = stripePriceIdForPlan(plan, input.interval);
    const existingSubscription = await database.subscription.findFirst({
      where: { userId: session!.user.id, stripeCustomerId: { not: null } },
      orderBy: { updatedAt: "desc" },
      select: { stripeCustomerId: true },
    });
    const baseUrl = env.APP_BASE_URL;
    const checkout = await stripe.checkout.sessions.create({
      mode: "subscription",
      client_reference_id: session!.user.id,
      customer: existingSubscription?.stripeCustomerId ?? undefined,
      customer_email: existingSubscription?.stripeCustomerId
        ? undefined
        : (session!.user.email ?? undefined),
      line_items: [{ price: priceId, quantity: 1 }],
      allow_promotion_codes: true,
      success_url: `${baseUrl}/account/billing?checkout=success`,
      cancel_url: `${baseUrl}/account/billing?checkout=cancelled`,
      metadata: {
        userId: session!.user.id,
        planCode: input.planCode,
        billingInterval: input.interval,
      },
      subscription_data: {
        metadata: {
          userId: session!.user.id,
          planCode: input.planCode,
          billingInterval: input.interval,
        },
      },
    });

    return NextResponse.json({ url: checkout.url });
  } catch (error) {
    return errorResponse(error);
  }
}
