import { getDatabase } from "@/lib/db";
import { getServerEnv } from "@/lib/env";

export const dynamic = "force-dynamic";

export async function GET() {
  const env = getServerEnv();
  const databaseConfigured = Boolean(env.DATABASE_URL);
  const database = getDatabase();
  let databaseStatus = databaseConfigured ? "unavailable" : "not_configured";

  if (database) {
    try {
      await database.$queryRaw`SELECT 1`;
      databaseStatus = "ready";
    } catch {
      databaseStatus = "unavailable";
    }
  }

  const ready = databaseStatus === "ready";

  return Response.json(
    {
      ready,
      checks: {
        application: "ready",
        database: databaseStatus,
      },
      timestamp: new Date().toISOString(),
    },
    {
      status: ready ? 200 : 503,
      headers: { "Cache-Control": "no-store" },
    },
  );
}
