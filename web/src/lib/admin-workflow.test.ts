import { describe, expect, it } from "vitest";

import { AlertState, RiskLevel, UserRole } from "@/generated/prisma/enums";
import {
  canInvokeAdminAction,
  evaluateAutoApprovalCandidate,
  isReviewableAlertState,
  normalizeEditableAlertFields,
  normalizeRejectionReason,
} from "@/lib/admin-workflow";

function session(role: UserRole, id = "user-1") {
  return {
    user: { id, role, email: `${id}@example.com` },
    expires: "2099-01-01T00:00:00.000Z",
  };
}

const existing = {
  headline: "Hot CPI release",
  summary: "Inflation surprise lifted rate pressure.",
  expectedReaction: "NQ may fade until yields cool.",
  riskWarning: "Wait for tape confirmation.",
  invalidation: "Yields reverse lower.",
  disclaimer: "Educational and informational use only.",
};

describe("admin workflow", () => {
  it("keeps admin mutations behind the admin role", () => {
    expect(canInvokeAdminAction(null)).toBe(false);
    expect(canInvokeAdminAction(session(UserRole.FREE_USER))).toBe(false);
    expect(canInvokeAdminAction(session(UserRole.PAID_SUBSCRIBER))).toBe(false);
    expect(canInvokeAdminAction(session(UserRole.ADMIN))).toBe(true);
  });

  it("only allows draft and pending alerts to be moderated", () => {
    expect(isReviewableAlertState(AlertState.DRAFT)).toBe(true);
    expect(isReviewableAlertState(AlertState.PENDING)).toBe(true);
    expect(isReviewableAlertState(AlertState.APPROVED)).toBe(false);
    expect(isReviewableAlertState(AlertState.SENT)).toBe(false);
  });

  it("normalizes editable fields without allowing blank required copy", () => {
    const normalized = normalizeEditableAlertFields(
      {
        headline: "  ",
        summary: "  Updated summary  ",
        expectedReaction: "",
        riskWarning: "  Updated risk  ",
        invalidation: "",
        disclaimer: "",
      },
      existing,
    );

    expect(normalized.headline).toBe(existing.headline);
    expect(normalized.summary).toBe("Updated summary");
    expect(normalized.expectedReaction).toBe(existing.expectedReaction);
    expect(normalized.riskWarning).toBe("Updated risk");
    expect(normalized.invalidation).toBe(existing.invalidation);
    expect(normalized.disclaimer).toBe(existing.disclaimer);
  });

  it("requires a useful rejection reason", () => {
    expect(normalizeRejectionReason("")).toEqual({
      ok: false,
      error: "A rejection reason is required.",
    });
    expect(normalizeRejectionReason(" duplicate headline ").ok).toBe(true);
  });

  it("keeps optional auto approval limited to reviewed high-confidence rules", () => {
    expect(
      evaluateAutoApprovalCandidate({
        enabled: true,
        eventFamily: "nfp",
        confidence: 88,
        riskLevel: RiskLevel.MEDIUM,
        hasRegimeConflict: false,
      }).allowed,
    ).toBe(true);
    expect(
      evaluateAutoApprovalCandidate({
        enabled: true,
        eventFamily: "earnings",
        confidence: 95,
        riskLevel: RiskLevel.LOW,
        hasRegimeConflict: false,
      }).allowed,
    ).toBe(false);
    expect(
      evaluateAutoApprovalCandidate({
        enabled: true,
        eventFamily: "cpi",
        confidence: 91,
        riskLevel: RiskLevel.HIGH,
        hasRegimeConflict: false,
      }).allowed,
    ).toBe(false);
  });
});
