import { PrismaPg } from "@prisma/adapter-pg";
import { config } from "dotenv";

import { PrismaClient } from "../src/generated/prisma/client";
import {
  createResendEmailSender,
  listDueEmailDeliveryAttempts,
  processDueEmailDeliveryAttempts,
  type DeliveryDispatchDatabase,
} from "../src/lib/delivery-dispatch";

config({ path: ".env.local", quiet: true });
config({ quiet: true });

function readNumberFlag(name: string, fallback: number) {
  const inline = process.argv.find((argument) =>
    argument.startsWith(`--${name}=`),
  );
  const raw = inline
    ? inline.split("=", 2)[1]
    : process.argv[process.argv.indexOf(`--${name}`) + 1];
  if (!raw || raw.startsWith("--")) return fallback;
  const parsed = Number(raw);
  return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : fallback;
}

async function main() {
  const databaseUrl = process.env.DATABASE_URL;
  if (!databaseUrl) {
    throw new Error("DATABASE_URL is required before processing deliveries.");
  }

  const dryRun = process.argv.includes("--dry-run");
  const limit = readNumberFlag("limit", 25);
  const maxAttempts = readNumberFlag("max-attempts", 5);
  const prisma = new PrismaClient({
    adapter: new PrismaPg({ connectionString: databaseUrl }),
  });
  const database = prisma as unknown as DeliveryDispatchDatabase;

  try {
    if (dryRun) {
      const attempts = await listDueEmailDeliveryAttempts(database, { limit });
      console.log(
        JSON.stringify(
          {
            dryRun: true,
            dueEmailAttempts: attempts.map((attempt) => ({
              id: attempt.id,
              status: attempt.status,
              attemptNumber: attempt.attemptNumber,
              headline: attempt.alert.headline,
              recipientUserId: attempt.user.id,
            })),
          },
          null,
          2,
        ),
      );
      return;
    }

    const summary = await processDueEmailDeliveryAttempts({
      database,
      limit,
      maxAttempts,
      emailSender: createResendEmailSender({
        apiKey: process.env.RESEND_API_KEY,
        from: process.env.AUTH_EMAIL_FROM,
      }),
    });

    console.log(JSON.stringify(summary, null, 2));
  } finally {
    await prisma.$disconnect();
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : error);
  process.exitCode = 1;
});
