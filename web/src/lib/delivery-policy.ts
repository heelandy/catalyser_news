import {
  AlertChannel,
  RiskLevel,
  type AlertChannel as AlertChannelValue,
  type MarketBias,
  type RiskLevel as RiskLevelValue,
} from "@/generated/prisma/enums";
import type { AlertPreferenceInput } from "@/lib/account-preferences";
import type { PlanEntitlements } from "@/lib/plan-catalog";

const riskRank: Record<RiskLevelValue, number> = {
  [RiskLevel.LOW]: 0,
  [RiskLevel.MEDIUM]: 1,
  [RiskLevel.HIGH]: 2,
  [RiskLevel.CRITICAL]: 3,
};

export type DeliveryAlert = {
  id: string;
  headline: string;
  summary: string;
  bias: MarketBias;
  expectedReaction: string;
  confidence: number;
  riskLevel: RiskLevelValue;
  reasoning: string;
  riskWarning: string;
  watchLevels: unknown;
  invalidation: string | null;
  disclaimer: string;
  createdAt: Date;
  expiresAt: Date | null;
  marketReaction: {
    eventFamily: string;
    symbol: string;
  } | null;
};

export type VerifiedChannels = {
  email: boolean;
  telegram: boolean;
  discord: boolean;
};

export type DeliveryPayload = {
  alertId: string;
  headline: string;
  summary: string;
  marketBias: MarketBias;
  expectedReaction: string;
  confidence: number;
  riskLevel: RiskLevelValue;
  shortReasoning: string;
  riskWarning: string;
  timestamp: string;
  expiresAt: string | null;
  timeSensitivity: string;
  watchLevels: unknown;
  invalidation: string | null;
  disclaimer: string;
};

function minuteOfDay(value: string) {
  const [hour, minute] = value.split(":").map(Number);
  return hour * 60 + minute;
}

function easternMinuteOfDay(now: Date) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(now);
  const hour = Number(parts.find((part) => part.type === "hour")?.value ?? 0);
  const minute = Number(
    parts.find((part) => part.type === "minute")?.value ?? 0,
  );
  return hour * 60 + minute;
}

function familyMatches(selected: string[], eventFamily: string) {
  if (!selected.length) return false;
  const family = eventFamily.toLowerCase();
  return selected.some((value) => {
    const normalized = value.toLowerCase();
    return (
      normalized === family ||
      family.startsWith(`${normalized}_`) ||
      family.includes(normalized)
    );
  });
}

function symbolMatches(selected: string[], symbol: string) {
  return selected.length > 0 && selected.includes(symbol.toUpperCase());
}

export function isQuietHoursActive(
  preference: AlertPreferenceInput,
  now = new Date(),
) {
  if (!preference.quietHours.enabled) return false;
  const current = easternMinuteOfDay(now);
  const start = minuteOfDay(preference.quietHours.start);
  const end = minuteOfDay(preference.quietHours.end);
  if (start === end) return true;
  if (start < end) return current >= start && current < end;
  return current >= start || current < end;
}

export function alertMatchesPreference({
  alert,
  preference,
  now = new Date(),
}: {
  alert: DeliveryAlert;
  preference: AlertPreferenceInput;
  now?: Date;
}) {
  if (alert.confidence < preference.minimumConfidence) return false;
  if (riskRank[alert.riskLevel] < riskRank[preference.minimumRiskLevel]) {
    return false;
  }
  if (isQuietHoursActive(preference, now)) return false;
  if (
    !familyMatches(
      preference.eventFamilies,
      alert.marketReaction?.eventFamily ?? "",
    )
  ) {
    return false;
  }
  if (
    !symbolMatches(preference.symbols, alert.marketReaction?.symbol ?? "NQ")
  ) {
    return false;
  }
  return true;
}

export function enabledDeliveryChannels({
  entitlements,
  preference,
  verified,
}: {
  entitlements: PlanEntitlements;
  preference: AlertPreferenceInput;
  verified: VerifiedChannels;
}) {
  const allowed = new Set(entitlements.channels);
  const channels: AlertChannelValue[] = [];
  if (
    preference.emailEnabled &&
    verified.email &&
    allowed.has(AlertChannel.EMAIL)
  ) {
    channels.push(AlertChannel.EMAIL);
  }
  if (
    preference.telegramEnabled &&
    verified.telegram &&
    allowed.has(AlertChannel.TELEGRAM)
  ) {
    channels.push(AlertChannel.TELEGRAM);
  }
  if (
    preference.discordEnabled &&
    verified.discord &&
    allowed.has(AlertChannel.DISCORD)
  ) {
    channels.push(AlertChannel.DISCORD);
  }
  return channels;
}

export function isDailyLimitAvailable(
  entitlements: PlanEntitlements,
  alertsQueuedToday: number,
) {
  return (
    entitlements.dailyAlertLimit === null ||
    alertsQueuedToday < entitlements.dailyAlertLimit
  );
}

export function nextRetryAtForPlan(
  entitlements: PlanEntitlements,
  now = new Date(),
) {
  return new Date(now.getTime() + entitlements.summaryDelayMinutes * 60_000);
}

export function retryDelaySeconds(attemptNumber: number) {
  const exponent = Math.max(0, attemptNumber - 1);
  return Math.min(3600, 60 * 2 ** exponent);
}

export function buildDeliveryPayload(alert: DeliveryAlert): DeliveryPayload {
  return {
    alertId: alert.id,
    headline: alert.headline,
    summary: alert.summary,
    marketBias: alert.bias,
    expectedReaction: alert.expectedReaction,
    confidence: alert.confidence,
    riskLevel: alert.riskLevel,
    shortReasoning: alert.reasoning,
    riskWarning: alert.riskWarning,
    timestamp: alert.createdAt.toISOString(),
    expiresAt: alert.expiresAt?.toISOString() ?? null,
    timeSensitivity: alert.expiresAt
      ? `Expires ${alert.expiresAt.toISOString()}`
      : "No explicit expiry set",
    watchLevels: alert.watchLevels,
    invalidation: alert.invalidation,
    disclaimer: alert.disclaimer,
  };
}
