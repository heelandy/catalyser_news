import { NextResponse } from "next/server";

import {
  BillingConfigurationError,
  requireStripeClient,
  requireStripeWebhookSecret,
} from "@/lib/billing/stripe-config";
import { processStripeEvent } from "@/lib/billing/stripe-sync";

export const runtime = "nodejs";

export async function POST(request: Request) {
  try {
    const stripe = requireStripeClient();
    const webhookSecret = requireStripeWebhookSecret();
    const signature = request.headers.get("stripe-signature");
    if (!signature) {
      return NextResponse.json(
        { error: "Missing Stripe signature." },
        { status: 400 },
      );
    }

    const payload = await request.text();
    const event = stripe.webhooks.constructEvent(
      payload,
      signature,
      webhookSecret,
    );
    const result = await processStripeEvent(event);

    return NextResponse.json({ received: true, ...result });
  } catch (error) {
    if (error instanceof BillingConfigurationError) {
      return NextResponse.json({ error: error.message }, { status: 503 });
    }
    if (
      error instanceof Error &&
      error.message.toLowerCase().includes("signature")
    ) {
      return NextResponse.json(
        { error: "Invalid Stripe signature." },
        { status: 400 },
      );
    }
    throw error;
  }
}
