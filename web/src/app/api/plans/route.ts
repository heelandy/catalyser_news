import { NextResponse } from "next/server";

import { publicPlanCatalog } from "@/lib/plan-catalog";

export function GET() {
  return NextResponse.json(
    { plans: publicPlanCatalog() },
    {
      headers: {
        "Cache-Control": "public, max-age=300, stale-while-revalidate=3600",
      },
    },
  );
}
