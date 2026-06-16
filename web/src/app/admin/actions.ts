"use server";

import { headers } from "next/headers";
import { revalidatePath } from "next/cache";

import { AlertState } from "@/generated/prisma/enums";
import {
  isReviewableAlertState,
  normalizeEditableAlertFields,
  normalizeRejectionReason,
  type EditableAlertFields,
} from "@/lib/admin-workflow";
import { queueApprovedAlert } from "@/lib/delivery-queue";
import { getRequiredDatabase } from "@/lib/db";
import {
  PROTECTED_FORM_SCOPES,
  verifyProtectedFormToken,
} from "@/lib/protected-form";
import { requireAdmin } from "@/lib/server-auth";

function formText(formData: FormData, key: string) {
  const value = formData.get(key);
  return typeof value === "string" ? value : "";
}

function editableFieldsFromForm(formData: FormData): EditableAlertFields {
  return {
    headline: formText(formData, "headline"),
    summary: formText(formData, "summary"),
    expectedReaction: formText(formData, "expectedReaction"),
    riskWarning: formText(formData, "riskWarning"),
    invalidation: formText(formData, "invalidation") || null,
    disclaimer: formText(formData, "disclaimer"),
  };
}

function requireAlertId(formData: FormData) {
  const alertId = formText(formData, "alertId").trim();
  if (!alertId) throw new Error("Missing alert id.");
  return alertId;
}

async function requestAuditContext() {
  const requestHeaders = await headers();
  return {
    ipAddress:
      requestHeaders.get("x-forwarded-for")?.split(",")[0]?.trim() ??
      requestHeaders.get("x-real-ip"),
    userAgent: requestHeaders.get("user-agent"),
  };
}

async function mutateReviewableAlert(
  formData: FormData,
  action: "alert.edit" | "alert.approve" | "alert.reject",
  mutate: (args: {
    alertId: string;
    adminUserId: string;
    fields: EditableAlertFields;
    rejectionReason: string | null;
  }) => Promise<void>,
) {
  const admin = await requireAdmin();
  verifyProtectedFormToken(formData, {
    scope: PROTECTED_FORM_SCOPES.adminAlertReview,
    userId: admin.id,
  });
  const alertId = requireAlertId(formData);
  const database = getRequiredDatabase();
  const existing = await database.alert.findUnique({
    where: { id: alertId },
    select: {
      state: true,
      headline: true,
      summary: true,
      expectedReaction: true,
      riskWarning: true,
      invalidation: true,
      disclaimer: true,
    },
  });

  if (!existing || !isReviewableAlertState(existing.state)) {
    throw new Error("This alert is no longer available for review.");
  }

  const fields = normalizeEditableAlertFields(
    editableFieldsFromForm(formData),
    existing,
  );
  const rawReason = formText(formData, "rejectionReason");
  const rejectionReason =
    action === "alert.reject" ? normalizeRejectionReason(rawReason) : null;
  if (rejectionReason && !rejectionReason.ok) {
    throw new Error(rejectionReason.error);
  }

  await mutate({
    alertId,
    adminUserId: admin.id,
    fields,
    rejectionReason: rejectionReason?.value ?? null,
  });
  revalidatePath("/admin");
}

export async function saveAlertEdits(formData: FormData) {
  await mutateReviewableAlert(formData, "alert.edit", async (args) => {
    const database = getRequiredDatabase();
    const auditContext = await requestAuditContext();
    await database.$transaction([
      database.alert.update({
        where: { id: args.alertId },
        data: args.fields,
      }),
      database.adminAuditLog.create({
        data: {
          actorUserId: args.adminUserId,
          action: "alert.edit",
          entityType: "Alert",
          entityId: args.alertId,
          reason: "Admin edited alert before fan-out.",
          ...auditContext,
        },
      }),
    ]);
  });
}

export async function approveAlert(formData: FormData) {
  await mutateReviewableAlert(formData, "alert.approve", async (args) => {
    const database = getRequiredDatabase();
    const auditContext = await requestAuditContext();
    await database.$transaction([
      database.alert.update({
        where: { id: args.alertId },
        data: {
          ...args.fields,
          state: AlertState.APPROVED,
          approvedById: args.adminUserId,
          approvedAt: new Date(),
          rejectedById: null,
          rejectedAt: null,
          rejectionReason: null,
        },
      }),
      database.adminAuditLog.create({
        data: {
          actorUserId: args.adminUserId,
          action: "alert.approve",
          entityType: "Alert",
          entityId: args.alertId,
          reason: "Admin approved alert for delivery queue.",
          ...auditContext,
        },
      }),
    ]);
    await queueApprovedAlert(args.alertId);
  });
}

export async function rejectAlert(formData: FormData) {
  await mutateReviewableAlert(formData, "alert.reject", async (args) => {
    const database = getRequiredDatabase();
    const auditContext = await requestAuditContext();
    await database.$transaction([
      database.alert.update({
        where: { id: args.alertId },
        data: {
          ...args.fields,
          state: AlertState.REJECTED,
          rejectedById: args.adminUserId,
          rejectedAt: new Date(),
          rejectionReason: args.rejectionReason,
          approvedById: null,
          approvedAt: null,
        },
      }),
      database.adminAuditLog.create({
        data: {
          actorUserId: args.adminUserId,
          action: "alert.reject",
          entityType: "Alert",
          entityId: args.alertId,
          reason: args.rejectionReason,
          ...auditContext,
        },
      }),
    ]);
  });
}
