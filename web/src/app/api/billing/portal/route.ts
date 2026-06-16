import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { authorizeRoute } from "@/lib/authz";
import {
  BillingConfigurationError,
  requireStripeClient,
} from "@/lib/billing/stripe-config";
import { getRequiredDatabase } from "@/lib/db";
import { getServerEnv } from "@/lib/env";
import { rejectCrossOriginRequest } from "@/lib/request-security";

export async function POST(request: Request) {
  try {
    const env = getServerEnv();
    const crossOrigin = rejectCrossOriginRequest(request, env.APP_BASE_URL);
    if (crossOrigin) return crossOrigin;

    const session = await auth();
    const decision = authorizeRoute(session);
    if (decision === "unauthenticated") {
      return NextResponse.json(
        { error: "Sign in before opening billing." },
        { status: 401 },
      );
    }

    const database = getRequiredDatabase();
    const subscription = await database.subscription.findFirst({
      where: { userId: session!.user.id, stripeCustomerId: { not: null } },
      orderBy: { updatedAt: "desc" },
      select: { stripeCustomerId: true },
    });
    if (!subscription?.stripeCustomerId) {
      return NextResponse.json(
        { error: "No Stripe customer exists for this account yet." },
        { status: 404 },
      );
    }

    const stripe = requireStripeClient();
    const baseUrl = env.APP_BASE_URL;
    const portal = await stripe.billingPortal.sessions.create({
      customer: subscription.stripeCustomerId,
      return_url: `${baseUrl}/account/billing`,
    });

    return NextResponse.json({ url: portal.url });
  } catch (error) {
    if (error instanceof BillingConfigurationError) {
      return NextResponse.json({ error: error.message }, { status: 503 });
    }
    throw error;
  }
}
