import { AlertState } from "@/generated/prisma/enums";
import type { PlanEntitlements } from "@/lib/plan-catalog";

export type AlertVisibilityInput = {
  state: AlertState;
  createdAt: Date;
  sentAt: Date | null;
};

export function alertAvailableAt(
  alert: AlertVisibilityInput,
  entitlements: PlanEntitlements,
) {
  const basis = alert.sentAt ?? alert.createdAt;
  return new Date(basis.getTime() + entitlements.summaryDelayMinutes * 60_000);
}

export function alertHistoryCutoff(
  entitlements: PlanEntitlements,
  now = new Date(),
) {
  if (entitlements.alertHistoryDays === null) return null;
  return new Date(
    now.getTime() - entitlements.alertHistoryDays * 24 * 60 * 60_000,
  );
}

export function canViewAlert(
  alert: AlertVisibilityInput,
  entitlements: PlanEntitlements,
  now = new Date(),
) {
  if (alert.state !== AlertState.SENT) return false;
  if (alertAvailableAt(alert, entitlements) > now) return false;

  const cutoff = alertHistoryCutoff(entitlements, now);
  if (!cutoff) return true;
  return (alert.sentAt ?? alert.createdAt) >= cutoff;
}

export function filterVisibleAlerts<T extends AlertVisibilityInput>(
  alerts: T[],
  entitlements: PlanEntitlements,
  now = new Date(),
) {
  return alerts.filter((alert) => canViewAlert(alert, entitlements, now));
}
