import { PrismaPg } from "@prisma/adapter-pg";
import { config } from "dotenv";

import { PrismaClient } from "../src/generated/prisma/client";
import { PLAN_CATALOG, PLAN_CODES } from "../src/lib/plan-catalog";

config({ path: ".env.local" });
config();

const databaseUrl = process.env.DATABASE_URL;

if (!databaseUrl) {
  throw new Error("Set DATABASE_URL before running npm run db:verify.");
}

const adapter = new PrismaPg({ connectionString: databaseUrl });
const prisma = new PrismaClient({ adapter });

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map(canonicalJson).join(",")}]`;
  }
  if (value && typeof value === "object") {
    const entries = Object.entries(value).sort(([left], [right]) =>
      left.localeCompare(right),
    );
    return `{${entries
      .map(([key, nested]) => `${JSON.stringify(key)}:${canonicalJson(nested)}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}
async function main() {
  const plans = await prisma.plan.findMany({
    orderBy: { priorityRank: "asc" },
    select: {
      code: true,
      name: true,
      monthlyPriceCents: true,
      quarterlyPriceCents: true,
      annualPriceCents: true,
      dailyAlertLimit: true,
      priorityRank: true,
      features: true,
    },
  });

  const planCodes = plans.map((plan) => plan.code);
  if (planCodes.join(",") !== PLAN_CODES.join(",")) {
    throw new Error(
      `Expected plans ${PLAN_CODES.join(", ")}, received ${planCodes.join(", ") || "none"}.`,
    );
  }

  for (const plan of plans) {
    const expected = PLAN_CATALOG[plan.code as keyof typeof PLAN_CATALOG];
    if (
      !expected ||
      plan.monthlyPriceCents !== expected.prices.MONTHLY ||
      plan.quarterlyPriceCents !== expected.prices.QUARTERLY ||
      plan.annualPriceCents !== expected.prices.ANNUAL ||
      plan.dailyAlertLimit !== expected.entitlements.dailyAlertLimit ||
      plan.priorityRank !== expected.priorityRank ||
      canonicalJson(plan.features) !==
        canonicalJson({ entitlementVersion: 1, ...expected.entitlements })
    ) {
      throw new Error(`Database plan ${plan.code} does not match the catalog.`);
    }
  }

  console.log(
    plans
      .map(
        (plan) =>
          `${plan.code}|${plan.name}|${plan.monthlyPriceCents}|${plan.quarterlyPriceCents}|${plan.annualPriceCents}`,
      )
      .join("\n"),
  );
}

main()
  .then(async () => {
    await prisma.$disconnect();
  })
  .catch(async (error) => {
    await prisma.$disconnect();
    throw error;
  });
