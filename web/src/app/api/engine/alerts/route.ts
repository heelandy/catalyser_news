import { ZodError } from "zod";

import {
  ENGINE_INGEST_SIGNATURE_HEADER,
  ENGINE_INGEST_TIMESTAMP_HEADER,
  parseEngineIngestPayload,
  verifyEngineIngestSignature,
} from "@/lib/engine-ingest-contract";
import { persistEngineIngestPayload } from "@/lib/engine-ingest-store";
import { getServerEnv } from "@/lib/env";

export const dynamic = "force-dynamic";

function jsonResponse(
  payload: Record<string, unknown>,
  status: number,
  headers?: HeadersInit,
) {
  return Response.json(payload, {
    status,
    headers: {
      "Cache-Control": "no-store",
      ...headers,
    },
  });
}

export async function POST(request: Request) {
  const env = getServerEnv();
  const body = await request.text();
  const signature = verifyEngineIngestSignature({
    secret: env.ENGINE_INGEST_SECRET,
    timestamp: request.headers.get(ENGINE_INGEST_TIMESTAMP_HEADER),
    signature: request.headers.get(ENGINE_INGEST_SIGNATURE_HEADER),
    body,
  });

  if (!signature.ok) {
    return jsonResponse(
      {
        ok: false,
        error: signature.error,
      },
      signature.status,
    );
  }

  let parsedJson: unknown;
  try {
    parsedJson = JSON.parse(body);
  } catch {
    return jsonResponse(
      { ok: false, error: "Request body must be valid JSON." },
      400,
    );
  }

  try {
    const payload = parseEngineIngestPayload(parsedJson);
    const result = await persistEngineIngestPayload(payload);
    return jsonResponse(
      {
        ok: true,
        duplicate: result.duplicate,
        alertId: result.alertId,
        marketReactionId: result.marketReactionId,
        newsEventId: result.newsEventId,
      },
      result.duplicate ? 200 : 201,
    );
  } catch (error) {
    if (error instanceof ZodError) {
      return jsonResponse(
        {
          ok: false,
          error: "Payload failed engine ingestion schema validation.",
          issues: error.issues.map((issue) => ({
            path: issue.path.join("."),
            message: issue.message,
          })),
        },
        400,
      );
    }
    console.error("engine alert ingestion failed", error);
    return jsonResponse({ ok: false, error: "Engine ingestion failed." }, 500);
  }
}
