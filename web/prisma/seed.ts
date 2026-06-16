import { PrismaPg } from "@prisma/adapter-pg";
import { config } from "dotenv";

import { PlanStatus, PrismaClient } from "../src/generated/prisma/client";
import {
  PLAN_CATALOG,
  PLAN_CODES,
  planFeaturesForDatabase,
} from "../src/lib/plan-catalog";

config({ path: ".env.local" });
config();

const databaseUrl = process.env.DATABASE_URL;

if (!databaseUrl) {
  throw new Error("Set DATABASE_URL before running npm run db:seed.");
}

const adapter = new PrismaPg({ connectionString: databaseUrl });
const prisma = new PrismaClient({ adapter });

async function main() {
  for (const code of PLAN_CODES) {
    const plan = PLAN_CATALOG[code];
    const record = {
      code: plan.code,
      name: plan.name,
      description: plan.description,
      status: PlanStatus.ACTIVE,
      monthlyPriceCents: plan.prices.MONTHLY,
      quarterlyPriceCents: plan.prices.QUARTERLY,
      annualPriceCents: plan.prices.ANNUAL,
      dailyAlertLimit: plan.entitlements.dailyAlertLimit,
      priorityRank: plan.priorityRank,
      features: planFeaturesForDatabase(plan),
    };

    await prisma.plan.upsert({
      where: { code },
      update: record,
      create: record,
    });
  }
}

main()
  .then(async () => {
    await prisma.$disconnect();
  })
  .catch(async (error) => {
    await prisma.$disconnect();
    throw error;
  });
