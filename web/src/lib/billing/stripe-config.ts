import "server-only";

import Stripe from "stripe";

import { getServerEnv } from "@/lib/env";

const STRIPE_API_VERSION = "2026-05-27.dahlia";

let stripeClient: Stripe | null | undefined;

export class BillingConfigurationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "BillingConfigurationError";
  }
}

export function getStripeClient() {
  if (stripeClient !== undefined) return stripeClient;

  const secretKey = getServerEnv().STRIPE_SECRET_KEY;
  if (!secretKey) {
    stripeClient = null;
    return stripeClient;
  }

  stripeClient = new Stripe(secretKey, {
    apiVersion: STRIPE_API_VERSION,
    appInfo: {
      name: "Market Catalyst Web",
      version: "0.1.0",
    },
  });
  return stripeClient;
}

export function requireStripeClient() {
  const stripe = getStripeClient();
  if (!stripe) {
    throw new BillingConfigurationError(
      "Stripe is not configured. Set STRIPE_SECRET_KEY in web/.env.local.",
    );
  }
  return stripe;
}

export function requireStripeWebhookSecret() {
  const secret = getServerEnv().STRIPE_WEBHOOK_SECRET;
  if (!secret) {
    throw new BillingConfigurationError(
      "Stripe webhook signing is not configured. Set STRIPE_WEBHOOK_SECRET in web/.env.local.",
    );
  }
  return secret;
}

export function isBillingConfigured() {
  const env = getServerEnv();
  return Boolean(env.STRIPE_SECRET_KEY && env.STRIPE_WEBHOOK_SECRET);
}
