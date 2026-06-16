import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const schema = readFileSync(
  path.join(process.cwd(), "prisma", "schema.prisma"),
  "utf8",
);

const requiredModels = [
  "User",
  "Account",
  "Session",
  "VerificationToken",
  "Plan",
  "Subscription",
  "Payment",
  "Invoice",
  "Coupon",
  "Alert",
  "AlertPreference",
  "NewsEvent",
  "MarketReaction",
  "AlertDeliveryAttempt",
  "DiscordConnection",
  "TelegramConnection",
  "IntegrationSetting",
  "IntegrationTestLog",
  "AdminAuditLog",
  "SecurityAuditLog",
];

const requiredEnums = [
  "UserRole",
  "SubscriptionState",
  "AlertState",
  "AlertChannel",
  "MarketBias",
  "RiskLevel",
  "IntegrationProvider",
  "IntegrationStatus",
];

describe("Phase 2 schema contract", () => {
  it("keeps the required commercial product models", () => {
    for (const model of requiredModels) {
      expect(schema).toMatch(new RegExp(`model\\s+${model}\\s+\\{`));
    }
  });

  it("keeps the required authorization and alert enums", () => {
    for (const enumName of requiredEnums) {
      expect(schema).toMatch(new RegExp(`enum\\s+${enumName}\\s+\\{`));
    }
  });

  it("keeps uniqueness, ownership, and operational indexes", () => {
    expect(schema).toContain("@@unique([provider, providerAccountId])");
    expect(schema).toMatch(/idempotencyKey\s+String\?\s+@unique/);
    expect(schema).toContain("@@index([userId, state])");
    expect(schema).toContain("@@index([state, createdAt])");
    expect(schema).toContain("@@index([status, nextRetryAt])");
    expect(schema).toContain("@@index([enabled, status])");
    expect(schema).toContain("@@index([provider, createdAt])");
    expect(schema).toContain("@@index([retainUntil])");
  });
});
