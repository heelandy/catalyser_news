import { randomBytes } from "node:crypto";

import { PrismaPg } from "@prisma/adapter-pg";
import { config } from "dotenv";
import { chromium } from "playwright-core";

import { PrismaClient, UserRole } from "../src/generated/prisma/client";

config({ path: ".env.local" });
config();

const baseUrl = process.env.DASHBOARD_VERIFY_URL ?? "http://127.0.0.1:3000";
const databaseUrl = process.env.DATABASE_URL;
const edgePath =
  process.env.EDGE_PATH ??
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";

if (!databaseUrl) {
  throw new Error("Set DATABASE_URL before verifying account dashboard pages.");
}

const prisma = new PrismaClient({
  adapter: new PrismaPg({ connectionString: databaseUrl }),
});

const email = "local-dashboard-verify@example.com";
const sessionToken = randomBytes(32).toString("hex");
const expires = new Date(Date.now() + 60 * 60 * 1000);

async function createSession() {
  const user = await prisma.user.upsert({
    where: { email },
    update: { role: UserRole.FREE_USER },
    create: {
      email,
      emailVerified: new Date(),
      role: UserRole.FREE_USER,
    },
  });

  await prisma.session.create({
    data: {
      sessionToken,
      userId: user.id,
      expires,
    },
  });

  return user.id;
}

async function main() {
  const userId = await createSession();
  const browser = await chromium.launch({
    executablePath: edgePath,
    headless: true,
  });

  try {
    const context = await browser.newContext({
      viewport: { width: 1366, height: 900 },
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
    await page.goto(`${baseUrl}/account/billing`, { waitUntil: "networkidle" });
    try {
      await page.getByRole("heading", { name: "Billing and access" }).waitFor();
    } catch (error) {
      await page.screenshot({
        path: "foundation-account-debug.png",
        fullPage: true,
      });
      console.log(`Failed on ${page.url()}`);
      throw error;
    }
    await page.screenshot({
      path: "foundation-account-billing.png",
      fullPage: true,
    });

    await page.setViewportSize({ width: 390, height: 920 });
    await page.goto(`${baseUrl}/account/preferences`, {
      waitUntil: "networkidle",
    });
    await page.getByRole("heading", { name: "Alert preferences" }).waitFor();
    await page.screenshot({
      path: "foundation-account-preferences-mobile.png",
      fullPage: true,
    });

    console.log("Account dashboard verification passed.");
  } finally {
    await browser.close();
    await prisma.user.delete({ where: { id: userId } }).catch(() => null);
    await prisma.$disconnect();
  }
}

main().catch(async (error) => {
  await prisma.$disconnect();
  throw error;
});
