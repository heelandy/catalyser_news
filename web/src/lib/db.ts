import "server-only";

import { PrismaPg } from "@prisma/adapter-pg";

import { PrismaClient } from "@/generated/prisma/client";
import { getServerEnv } from "@/lib/env";

const globalDatabase = globalThis as typeof globalThis & {
  marketCatalystDatabase?: PrismaClient;
};

export function getDatabase() {
  const databaseUrl = getServerEnv().DATABASE_URL;
  if (!databaseUrl) {
    return null;
  }

  if (!globalDatabase.marketCatalystDatabase) {
    const adapter = new PrismaPg({ connectionString: databaseUrl });
    globalDatabase.marketCatalystDatabase = new PrismaClient({ adapter });
  }

  return globalDatabase.marketCatalystDatabase;
}

export function getRequiredDatabase() {
  const database = getDatabase();
  if (!database) {
    throw new Error("DATABASE_URL is required for this server operation.");
  }

  return database;
}
