import "server-only";

import { readFile } from "node:fs/promises";
import path from "node:path";

import { getServerEnv } from "@/lib/env";

type PipelineStatus = {
  cycle?: number;
  finished_at?: string | null;
  ok?: boolean;
  failed_stage?: string;
  loop_seconds?: number;
};

type AlertSummary = {
  latest_alerts?: unknown[];
  signal_count?: number;
  current_signal_count?: number;
};

async function readJson<T>(filePath: string): Promise<T | null> {
  try {
    return JSON.parse(await readFile(filePath, "utf8")) as T;
  } catch {
    return null;
  }
}

async function loadRoadmap(root: string) {
  try {
    const text = await readFile(path.join(root, "expectationAPP"), "utf8");
    const completed = (text.match(/^- \[x\]/gm) ?? []).length;
    const pending = (text.match(/^- \[ \]/gm) ?? []).length;
    return { completed, pending, total: completed + pending };
  } catch {
    return { completed: 0, pending: 0, total: 0 };
  }
}

export async function loadFoundationSnapshot() {
  const env = getServerEnv();
  const root = path.resolve(
    env.CATALYST_ENGINE_ROOT || path.join(process.cwd(), ".."),
  );
  const [status, alertSummary, roadmap] = await Promise.all([
    readJson<PipelineStatus>(path.join(root, "macro_pipeline_status.json")),
    readJson<AlertSummary>(
      path.join(root, "macro_pipeline_alert_summary.json"),
    ),
    loadRoadmap(root),
  ]);

  const finishedAt = status?.finished_at ?? null;
  const ageSeconds = finishedAt
    ? (Date.now() - new Date(finishedAt).getTime()) / 1000
    : Number.POSITIVE_INFINITY;
  const staleAfter = Math.max(180, (status?.loop_seconds ?? 60) * 3);
  const stale = !Number.isFinite(ageSeconds) || ageSeconds > staleAfter;
  const healthy = Boolean(status?.ok) && !stale;
  const tone = status && !status.ok ? "error" : stale ? "stale" : "healthy";
  const label = healthy
    ? "Catalyst engine current"
    : status?.ok
      ? "Catalyst engine stale"
      : "Catalyst engine needs attention";
  const detail = status?.failed_stage
    ? `Last failure: ${status.failed_stage}`
    : stale
      ? "The web foundation is available, but the local pipeline has not refreshed recently."
      : "The local Python engine completed within its expected refresh window.";

  return {
    pipeline: {
      cycle: status?.cycle ?? null,
      ok: Boolean(status?.ok),
      finishedAt,
      tone,
      label,
      detail,
    },
    alerts: {
      latestCount: alertSummary?.latest_alerts?.length ?? 0,
      totalSignals:
        alertSummary?.current_signal_count ?? alertSummary?.signal_count ?? 0,
    },
    database: { configured: Boolean(env.DATABASE_URL) },
    roadmap,
  };
}
