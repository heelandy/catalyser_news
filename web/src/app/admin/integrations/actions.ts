"use server";

import { headers } from "next/headers";
import { revalidatePath } from "next/cache";

import { getRequiredDatabase } from "@/lib/db";
import {
  buildIntegrationSettingUpdate,
  definitionForProvider,
  loadIntegrationCards,
  localIntegrationTest,
  parseIntegrationProvider,
} from "@/lib/integration-settings";
import {
  PROTECTED_FORM_SCOPES,
  verifyProtectedFormToken,
} from "@/lib/protected-form";
import { requireAdmin } from "@/lib/server-auth";

async function requestAuditContext() {
  const requestHeaders = await headers();
  return {
    ipAddress:
      requestHeaders.get("x-forwarded-for")?.split(",")[0]?.trim() ??
      requestHeaders.get("x-real-ip"),
    userAgent: requestHeaders.get("user-agent"),
  };
}

async function requireIntegrationMutation(formData: FormData) {
  const admin = await requireAdmin();
  verifyProtectedFormToken(formData, {
    scope: PROTECTED_FORM_SCOPES.adminIntegrationSettings,
    userId: admin.id,
  });
  return {
    admin,
    provider: parseIntegrationProvider(formData.get("provider")),
  };
}

export async function saveIntegrationSettings(formData: FormData) {
  const { admin, provider } = await requireIntegrationMutation(formData);
  const definition = definitionForProvider(provider);
  const database = getRequiredDatabase();
  const existing = await database.integrationSetting.findUnique({
    where: { provider },
    select: {
      publicConfig: true,
      encryptedSecrets: true,
      maskedSecrets: true,
    },
  });
  const update = buildIntegrationSettingUpdate({
    provider,
    formData,
    existing,
  });
  const auditContext = await requestAuditContext();

  await database.$transaction(async (tx) => {
    const setting = await tx.integrationSetting.upsert({
      where: { provider },
      create: {
        ...update.data,
        updatedById: admin.id,
      },
      update: {
        ...update.data,
        updatedById: admin.id,
      },
    });
    await tx.adminAuditLog.create({
      data: {
        actorUserId: admin.id,
        action: "integration.update",
        entityType: "IntegrationSetting",
        entityId: setting.id,
        reason: `Updated ${definition.displayName} integration settings.`,
        metadata: {
          provider,
          status: update.data.status,
          enabled: update.data.enabled,
          changedSecretKeys: update.changedSecretKeys,
          missingRequiredKeys: update.missingRequiredKeys,
        },
        ...auditContext,
      },
    });
  });

  revalidatePath("/admin/integrations");
}

export async function testIntegrationSettings(formData: FormData) {
  const { admin, provider } = await requireIntegrationMutation(formData);
  const database = getRequiredDatabase();
  const cards = await loadIntegrationCards(database);
  const card = cards.find((item) => item.provider === provider);
  if (!card) throw new Error("Unsupported integration provider.");
  const result = localIntegrationTest(card);
  const auditContext = await requestAuditContext();

  await database.$transaction(async (tx) => {
    if (card.id) {
      await tx.integrationSetting.update({
        where: { id: card.id },
        data: {
          lastTestStatus: result.status,
          lastTestMessage: result.message,
          lastTestedAt: new Date(),
          status: result.status,
        },
      });
    }
    await tx.integrationTestLog.create({
      data: {
        settingId: card.id,
        provider,
        status: result.status,
        message: result.message,
        actorUserId: admin.id,
        metadata: {
          source: card.source,
          missingRequiredKeys: card.missingRequiredKeys,
        },
      },
    });
    await tx.adminAuditLog.create({
      data: {
        actorUserId: admin.id,
        action: "integration.test",
        entityType: "IntegrationSetting",
        entityId: card.id,
        reason: result.message,
        metadata: {
          provider,
          status: result.status,
          source: card.source,
        },
        ...auditContext,
      },
    });
  });

  revalidatePath("/admin/integrations");
}
