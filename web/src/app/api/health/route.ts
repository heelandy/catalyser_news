import { getServerEnv } from "@/lib/env";

export const dynamic = "force-dynamic";

export function GET() {
  const env = getServerEnv();
  return Response.json(
    {
      ok: true,
      service: "market-catalyst-web",
      environment: env.NODE_ENV,
      timestamp: new Date().toISOString(),
    },
    { headers: { "Cache-Control": "no-store" } },
  );
}
