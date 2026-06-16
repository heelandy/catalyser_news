import { PrismaPg } from "@prisma/adapter-pg";
import { config } from "dotenv";
import Stripe from "stripe";

import { BillingInterval, PrismaClient } from "../src/generated/prisma/client";
import { PLAN_CATALOG, PLAN_CODES } from "../src/lib/plan-catalog";

config({ path: ".env.local" });
config();

const databaseUrl = process.env.DATABASE_URL;
const stripeSecretKey = process.env.STRIPE_SECRET_KEY;
const dryRun = process.argv.includes("--dry-run");
const allowLive = process.argv.includes("--live");

if (!databaseUrl)
  throw new Error("Set DATABASE_URL before syncing Stripe catalog.");
if (!stripeSecretKey)
  throw new Error("Set STRIPE_SECRET_KEY before syncing Stripe catalog.");
if (!allowLive && !stripeSecretKey.startsWith("sk_test_")) {
  throw new Error("Refusing to sync a non-test Stripe key without --live.");
}

const stripe = new Stripe(stripeSecretKey, { apiVersion: "2026-05-27.dahlia" });
const prisma = new PrismaClient({
  adapter: new PrismaPg({ connectionString: databaseUrl }),
});

function priceField(interval: BillingInterval) {
  if (interval === BillingInterval.MONTHLY)
    return "stripeMonthlyPriceId" as const;
  if (interval === BillingInterval.QUARTERLY)
    return "stripeQuarterlyPriceId" as const;
  return "stripeAnnualPriceId" as const;
}

function recurring(interval: BillingInterval) {
  if (interval === BillingInterval.QUARTERLY)
    return { interval: "month" as const, interval_count: 3 };
  if (interval === BillingInterval.ANNUAL)
    return { interval: "year" as const, interval_count: 1 };
  return { interval: "month" as const, interval_count: 1 };
}

async function main() {
  for (const code of PLAN_CODES) {
    if (code === "free") continue;
    const catalogPlan = PLAN_CATALOG[code];
    const plan = await prisma.plan.findUniqueOrThrow({ where: { code } });
    let productId = plan.stripeProductId;

    if (!productId) {
      if (dryRun) {
        console.log(`[dry-run] create product for ${code}`);
        continue;
      }
      const product = await stripe.products.create({
        name: catalogPlan.name,
        description: catalogPlan.description,
        metadata: { planCode: code },
      });
      productId = product.id;
      await prisma.plan.update({
        where: { code },
        data: { stripeProductId: productId },
      });
    }

    for (const interval of [
      BillingInterval.MONTHLY,
      BillingInterval.QUARTERLY,
      BillingInterval.ANNUAL,
    ]) {
      const field = priceField(interval);
      if (plan[field]) continue;
      const amount = catalogPlan.prices[interval];
      if (dryRun) {
        console.log(
          `[dry-run] create ${interval} price for ${code}: ${amount}`,
        );
        continue;
      }
      const price = await stripe.prices.create({
        currency: "usd",
        unit_amount: amount,
        product: productId,
        recurring: recurring(interval),
        metadata: { planCode: code, billingInterval: interval },
      });
      await prisma.plan.update({
        where: { code },
        data: { [field]: price.id },
      });
      console.log(`${code}|${interval}|${price.id}`);
    }
  }
}

main()
  .then(async () => prisma.$disconnect())
  .catch(async (error) => {
    await prisma.$disconnect();
    throw error;
  });
