import type { Session } from "next-auth";

import {
  AlertState,
  RiskLevel,
  UserRole,
  type AlertState as AlertStateValue,
  type RiskLevel as RiskLevelValue,
} from "@/generated/prisma/enums";
import { authorizeRoute } from "@/lib/authz";

const reviewableAlertStates = new Set<AlertStateValue>([
  AlertState.DRAFT,
  AlertState.PENDING,
]);

const reviewedAutoApprovalFamilies = new Set([
  "cpi",
  "fomc",
  "ism",
  "jobless_claims",
  "nfp",
]);

export type EditableAlertFields = {
  headline: string;
  summary: string;
  expectedReaction: string;
  riskWarning: string;
  invalidation: string | null;
  disclaimer: string;
};

type AutoApprovalCandidate = {
  enabled: boolean;
  eventFamily: string | null;
  confidence: number;
  riskLevel: RiskLevelValue;
  hasRegimeConflict: boolean;
};

function cleanText(value: string, fallback: string, maxLength: number) {
  const trimmed = value.trim();
  return (trimmed || fallback).slice(0, maxLength);
}

function cleanOptionalText(value: string, fallback: string | null) {
  const trimmed = value.trim();
  if (trimmed) return trimmed.slice(0, 1200);
  return fallback;
}

export function isReviewableAlertState(state: AlertStateValue) {
  return reviewableAlertStates.has(state);
}

export function canInvokeAdminAction(session: Session | null) {
  return authorizeRoute(session, UserRole.ADMIN) === "allowed";
}

export function normalizeEditableAlertFields(
  input: EditableAlertFields,
  existing: EditableAlertFields,
): EditableAlertFields {
  return {
    headline: cleanText(input.headline, existing.headline, 280),
    summary: cleanText(input.summary, existing.summary, 1800),
    expectedReaction: cleanText(
      input.expectedReaction,
      existing.expectedReaction,
      1800,
    ),
    riskWarning: cleanText(input.riskWarning, existing.riskWarning, 1200),
    invalidation: cleanOptionalText(
      input.invalidation ?? "",
      existing.invalidation,
    ),
    disclaimer: cleanText(input.disclaimer, existing.disclaimer, 1200),
  };
}

export function normalizeRejectionReason(value: string) {
  const reason = value.trim();
  if (reason.length < 3) {
    return {
      ok: false as const,
      error: "A rejection reason is required.",
    };
  }
  return {
    ok: true as const,
    value: reason.slice(0, 1200),
  };
}

export function evaluateAutoApprovalCandidate({
  enabled,
  eventFamily,
  confidence,
  riskLevel,
  hasRegimeConflict,
}: AutoApprovalCandidate) {
  if (!enabled) {
    return { allowed: false, reason: "Auto approval is disabled." };
  }
  const family = eventFamily?.toLowerCase().trim() ?? "";
  if (!reviewedAutoApprovalFamilies.has(family)) {
    return { allowed: false, reason: "Event family is not reviewed." };
  }
  if (confidence < 85) {
    return { allowed: false, reason: "Confidence is below 85%." };
  }
  if (riskLevel === RiskLevel.HIGH || riskLevel === RiskLevel.CRITICAL) {
    return { allowed: false, reason: "Risk level requires manual review." };
  }
  if (hasRegimeConflict) {
    return { allowed: false, reason: "Live-regime conflict requires review." };
  }
  return { allowed: true, reason: "Reviewed high-confidence rule matched." };
}
