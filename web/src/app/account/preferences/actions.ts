"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { auth } from "@/auth";
import { parseAlertPreferenceForm } from "@/lib/account-preferences";
import { loadAccountSnapshot } from "@/lib/account-data";
import { authorizeRoute } from "@/lib/authz";
import { getRequiredDatabase } from "@/lib/db";
import {
  PROTECTED_FORM_SCOPES,
  verifyProtectedFormToken,
} from "@/lib/protected-form";

export async function saveAlertPreferences(formData: FormData) {
  const session = await auth();
  if (authorizeRoute(session) === "unauthenticated") {
    redirect("/sign-in?callbackUrl=%2Faccount%2Fpreferences");
  }

  verifyProtectedFormToken(formData, {
    scope: PROTECTED_FORM_SCOPES.accountPreferences,
    userId: session!.user.id,
  });

  const snapshot = await loadAccountSnapshot(session!.user);
  const input = parseAlertPreferenceForm(formData, snapshot.entitlements);
  const database = getRequiredDatabase();

  await database.alertPreference.upsert({
    where: { userId: session!.user.id },
    update: {
      planId: snapshot.currentSubscription?.planId,
      emailEnabled: input.emailEnabled,
      telegramEnabled: input.telegramEnabled,
      discordEnabled: input.discordEnabled,
      minimumConfidence: input.minimumConfidence,
      minimumRiskLevel: input.minimumRiskLevel,
      eventFamilies: input.eventFamilies,
      symbols: input.symbols,
      quietHours: input.quietHours,
    },
    create: {
      userId: session!.user.id,
      planId: snapshot.currentSubscription?.planId,
      emailEnabled: input.emailEnabled,
      telegramEnabled: input.telegramEnabled,
      discordEnabled: input.discordEnabled,
      minimumConfidence: input.minimumConfidence,
      minimumRiskLevel: input.minimumRiskLevel,
      eventFamilies: input.eventFamilies,
      symbols: input.symbols,
      quietHours: input.quietHours,
    },
  });

  revalidatePath("/account/preferences");
}
