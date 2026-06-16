import { randomBytes } from "node:crypto";

import { PrismaPg } from "@prisma/adapter-pg";
import { config } from "dotenv";
import { chromium } from "playwright-core";

import {
  AlertState,
  BillingInterval,
  MarketBias,
  RiskLevel,
  SubscriptionState,
  UserRole,
} from "../src/generated/prisma/enums";
import { PrismaClient } from "../src/generated/prisma/client";

config({ path: ".env.local" });
config();

const baseUrl = process.env.DASHBOARD_VERIFY_URL ?? "http://127.0.0.1:3000";
const databaseUrl = process.env.DATABASE_URL;
const edgePath =
  process.env.EDGE_PATH ??
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";

if (!databaseUrl) {
  throw new Error("Set DATABASE_URL before verifying admin dashboard pages.");
}

const prisma = new PrismaClient({
  adapter: new PrismaPg({ connectionString: databaseUrl }),
});

const suffix = randomBytes(6).toString("hex");
const email = `local-admin-verify-${suffix}@example.com`;
const subscriberEmail = `local-subscriber-verify-${suffix}@example.com`;
const sessionToken = randomBytes(32).toString("hex");
const expires = new Date(Date.now() + 60 * 60 * 1000);
const sourceEventId = `verify-admin-${suffix}`;
const sourceFingerprint = `verify-admin-alert-${suffix}`;

async function seedAdminDashboard() {
  const basicPlan = await prisma.plan.findUnique({
    where: { code: "basic" },
    select: { id: true },
  });
  if (!basicPlan) {
    throw new Error("Basic plan must be seeded before admin verification.");
  }

  const [admin, subscriber] = await Promise.all([
    prisma.user.create({
      data: {
        email,
        emailVerified: new Date(),
        role: UserRole.ADMIN,
      },
    }),
    prisma.user.create({
      data: {
        email: subscriberEmail,
        emailVerified: new Date(),
        role: UserRole.PAID_SUBSCRIBER,
      },
    }),
  ]);

  await Promise.all([
    prisma.session.create({
      data: {
        sessionToken,
        userId: admin.id,
        expires,
      },
    }),
    prisma.subscription.create({
      data: {
        userId: subscriber.id,
        planId: basicPlan.id,
        state: SubscriptionState.ACTIVE,
        billingInterval: BillingInterval.MONTHLY,
        currentPeriodStart: new Date(Date.now() - 24 * 60 * 60 * 1000),
        currentPeriodEnd: new Date(Date.now() + 30 * 24 * 60 * 60 * 1000),
      },
    }),
    prisma.alertPreference.create({
      data: {
        userId: subscriber.id,
        planId: basicPlan.id,
        emailEnabled: true,
        telegramEnabled: false,
        discordEnabled: false,
        minimumConfidence: 60,
        minimumRiskLevel: RiskLevel.LOW,
        eventFamilies: ["nfp"],
        symbols: ["NQ"],
        quietHours: {
          enabled: false,
          start: "16:00",
          end: "08:00",
        },
      },
    }),
  ]);

  const newsEvent = await prisma.newsEvent.create({
    data: {
      source: "verify",
      sourceEventId,
      publisher: "local",
      symbol: "NQ",
      eventFamily: "nfp",
      headline: "Verification NFP surprise headline",
      summary: "Seed data for the admin dashboard verification.",
      occurredAt: new Date(),
      rawPayload: { verify: true },
    },
  });

  const reaction = await prisma.marketReaction.create({
    data: {
      newsEventId: newsEvent.id,
      eventFamily: "nfp",
      symbol: "NQ",
      releaseTime: new Date(),
      actualValue: "172K",
      forecastValue: "80K",
      previousValue: "179K",
      releaseRuleBias: MarketBias.BEARISH,
      liveRegimeBias: MarketBias.BEARISH,
      finalBias: MarketBias.BEARISH,
      bullishProbability: 22,
      confidence: 82,
      riskLevel: RiskLevel.MEDIUM,
      tradeState: "no_long_wait_for_reclaim",
      expectedReaction:
        "Rates pressure should weigh on NQ until tape reclaims.",
      reasoning: "Hot labor print can lift Fed hike odds and pressure growth.",
      riskWarning: "Wait for post-release tape confirmation.",
      watchLevels: { nq: ["reclaim", "prior low"] },
      invalidation: "Yields fade and NQ reclaims the opening range.",
      expiresAt: new Date(Date.now() + 2 * 60 * 60 * 1000),
    },
  });

  const alert = await prisma.alert.create({
    data: {
      marketReactionId: reaction.id,
      state: AlertState.PENDING,
      headline: "Hot labor print pressures NQ",
      summary: "NFP surprise is bearish for growth until tape confirms.",
      bias: MarketBias.BEARISH,
      expectedReaction: "Avoid long NQ until reclaim confirmation.",
      confidence: 82,
      riskLevel: RiskLevel.MEDIUM,
      reasoning: "Labor strength can renew inflation and Fed pressure.",
      riskWarning: "Do not chase the first candle.",
      watchLevels: { nq: ["prior low", "VWAP"] },
      invalidation: "NQ reclaims VWAP with yields down.",
      disclaimer: "Educational and informational use only.",
      sourceFingerprint,
      idempotencyKey: sourceFingerprint,
      expiresAt: new Date(Date.now() + 2 * 60 * 60 * 1000),
    },
  });

  return {
    adminId: admin.id,
    subscriberId: subscriber.id,
    alertId: alert.id,
    reactionId: reaction.id,
    newsEventId: newsEvent.id,
  };
}

async function cleanup(seed?: {
  adminId: string;
  subscriberId: string;
  alertId: string;
  reactionId: string;
  newsEventId: string;
}) {
  if (seed?.alertId) {
    await prisma.alertDeliveryAttempt
      .deleteMany({ where: { alertId: seed.alertId } })
      .catch(() => null);
  }
  await prisma.alert
    .deleteMany({ where: { sourceFingerprint } })
    .catch(() => null);
  if (seed?.reactionId) {
    await prisma.marketReaction
      .delete({ where: { id: seed.reactionId } })
      .catch(() => null);
  }
  if (seed?.newsEventId) {
    await prisma.newsEvent
      .delete({ where: { id: seed.newsEventId } })
      .catch(() => null);
  }
  await prisma.session
    .deleteMany({ where: { sessionToken } })
    .catch(() => null);
  await prisma.user
    .deleteMany({ where: { email: { in: [email, subscriberEmail] } } })
    .catch(() => null);
}

async function main() {
  const seed = await seedAdminDashboard();
  const browser = await chromium.launch({
    executablePath: edgePath,
    headless: true,
  });

  try {
    const context = await browser.newContext({
      viewport: { width: 1440, height: 1050 },
    });
    await context.addCookies([
      {
        name: "authjs.session-token",
        value: sessionToken,
        url: baseUrl,
        httpOnly: true,
        sameSite: "Lax",
        expires: Math.floor(expires.getTime() / 1000),
      },
    ]);

    const page = await context.newPage();
    await page.goto(`${baseUrl}/admin`, { waitUntil: "networkidle" });
    await page.getByRole("heading", { name: "Admin operations" }).waitFor();
    await page.getByRole("heading", { name: "Review queue" }).waitFor();
    await page.locator('input[name="headline"]').first().waitFor();
    await page.screenshot({
      path: "foundation-admin-dashboard.png",
      fullPage: true,
    });

    await page.getByRole("button", { name: "Approve" }).first().click();
    await page.waitForLoadState("networkidle");

    let attempts = await prisma.alertDeliveryAttempt.findMany({
      where: { alertId: seed.alertId, userId: seed.subscriberId },
    });
    for (let index = 0; index < 20 && attempts.length === 0; index += 1) {
      await page.waitForTimeout(250);
      attempts = await prisma.alertDeliveryAttempt.findMany({
        where: { alertId: seed.alertId, userId: seed.subscriberId },
      });
    }

    if (attempts.length !== 1) {
      throw new Error(
        `Expected one seeded-subscriber delivery attempt, got ${attempts.length}.`,
      );
    }
    const attempt = attempts[0];
    if (
      attempt.channel !== "EMAIL" ||
      attempt.status !== "QUEUED" ||
      !attempt.payloadDigest ||
      !attempt.idempotencyKey
    ) {
      throw new Error("Queued delivery attempt did not match the contract.");
    }

    console.log("Admin dashboard and delivery queue verification passed.");
  } finally {
    await browser.close();
    await cleanup(seed);
    await prisma.$disconnect();
  }
}

main().catch(async (error) => {
  await cleanup();
  await prisma.$disconnect();
  throw error;
});
