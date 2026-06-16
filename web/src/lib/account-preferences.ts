import { AlertChannel, RiskLevel } from "@/generated/prisma/enums";
import type { PlanEntitlements } from "@/lib/plan-catalog";

export const EVENT_FAMILY_OPTIONS = [
  "nfp",
  "cpi",
  "fomc",
  "jobless_claims",
  "ism",
  "retail_sales",
] as const;

export const SYMBOL_OPTIONS = ["NQ", "ES", "YM", "RTY"] as const;

export type QuietHours = {
  enabled: boolean;
  start: string;
  end: string;
};

export type AlertPreferenceInput = {
  emailEnabled: boolean;
  telegramEnabled: boolean;
  discordEnabled: boolean;
  minimumConfidence: number;
  minimumRiskLevel: RiskLevel;
  eventFamilies: string[];
  symbols: string[];
  quietHours: QuietHours;
};

function valuesFromForm(formData: FormData, key: string) {
  return formData
    .getAll(key)
    .filter((value): value is string => typeof value === "string");
}

function confidenceFromForm(value: FormDataEntryValue | null) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return 60;
  return Math.min(100, Math.max(0, Math.round(parsed)));
}

function riskLevelFromForm(value: FormDataEntryValue | null) {
  return Object.values(RiskLevel).includes(value as RiskLevel)
    ? (value as RiskLevel)
    : RiskLevel.LOW;
}

function timeValue(value: FormDataEntryValue | null, fallback: string) {
  if (typeof value !== "string") return fallback;
  return /^\d{2}:\d{2}$/.test(value) ? value : fallback;
}

function allowedValues(values: string[], allowed: readonly string[]) {
  return values.filter((value) => allowed.includes(value));
}

export function parseAlertPreferenceForm(
  formData: FormData,
  entitlements: PlanEntitlements,
): AlertPreferenceInput {
  const channels = new Set(entitlements.channels);
  return {
    emailEnabled:
      channels.has(AlertChannel.EMAIL) && formData.get("emailEnabled") === "on",
    telegramEnabled:
      channels.has(AlertChannel.TELEGRAM) &&
      formData.get("telegramEnabled") === "on",
    discordEnabled:
      channels.has(AlertChannel.DISCORD) &&
      formData.get("discordEnabled") === "on",
    minimumConfidence: confidenceFromForm(formData.get("minimumConfidence")),
    minimumRiskLevel: riskLevelFromForm(formData.get("minimumRiskLevel")),
    eventFamilies: allowedValues(
      valuesFromForm(formData, "eventFamilies"),
      EVENT_FAMILY_OPTIONS,
    ),
    symbols: allowedValues(valuesFromForm(formData, "symbols"), SYMBOL_OPTIONS),
    quietHours: {
      enabled: formData.get("quietHoursEnabled") === "on",
      start: timeValue(formData.get("quietHoursStart"), "16:00"),
      end: timeValue(formData.get("quietHoursEnd"), "08:00"),
    },
  };
}

export function defaultAlertPreference(
  entitlements: PlanEntitlements,
): AlertPreferenceInput {
  const channels = new Set(entitlements.channels);
  return {
    emailEnabled: channels.has(AlertChannel.EMAIL),
    telegramEnabled: false,
    discordEnabled: false,
    minimumConfidence: 60,
    minimumRiskLevel: RiskLevel.LOW,
    eventFamilies: [...EVENT_FAMILY_OPTIONS],
    symbols: ["NQ"],
    quietHours: {
      enabled: false,
      start: "16:00",
      end: "08:00",
    },
  };
}
