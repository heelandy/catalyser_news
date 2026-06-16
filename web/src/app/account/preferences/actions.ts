"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { auth } from "@/auth";
import { AlertChannel } from "@/generated/prisma/enums";
import { parseAlertPreferenceForm } from "@/lib/account-preferences";
import { loadAccountSnapshot } from "@/lib/account-data";
import { authorizeRoute } from "@/lib/authz";
import { getRequiredDatabase } from "@/lib/db";
import {
  DiscordConnectionError,
  encryptDiscordWebhookToken,
  parseDiscordWebhookUrl,
  sendDiscordWebhookTest,
} from "@/lib/discord-connection";
import {
  PROTECTED_FORM_SCOPES,
  verifyProtectedFormToken,
} from "@/lib/protected-form";
import {
  generateTelegramVerificationCode,
  hashTelegramVerificationCode,
} from "@/lib/telegram-connection";

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

export async function startTelegramConnection(formData: FormData) {
  const session = await auth();
  if (authorizeRoute(session) === "unauthenticated") {
    redirect("/sign-in?callbackUrl=%2Faccount%2Fpreferences");
  }

  verifyProtectedFormToken(formData, {
    scope: PROTECTED_FORM_SCOPES.accountTelegramConnect,
    userId: session!.user.id,
  });

  const snapshot = await loadAccountSnapshot(session!.user);
  if (!snapshot.entitlements.channels.includes(AlertChannel.TELEGRAM)) {
    throw new Error("Telegram alerts are not available for this plan.");
  }

  const database = getRequiredDatabase();
  const code = generateTelegramVerificationCode();
  const verificationCodeHash = hashTelegramVerificationCode({
    userId: session!.user.id,
    code,
  });
  const existing = await database.telegramConnection.findFirst({
    where: { userId: session!.user.id },
    orderBy: { updatedAt: "desc" },
  });

  if (existing) {
    await database.telegramConnection.update({
      where: { id: existing.id },
      data: {
        telegramUserId: null,
        chatId: null,
        verificationCodeHash,
        verifiedAt: null,
        disabledAt: null,
      },
    });
  } else {
    await database.telegramConnection.create({
      data: {
        userId: session!.user.id,
        verificationCodeHash,
      },
    });
  }

  revalidatePath("/account/preferences");
  redirect(`/account/preferences?telegramCode=${encodeURIComponent(code)}`);
}

export async function disconnectTelegramConnection(formData: FormData) {
  const session = await auth();
  if (authorizeRoute(session) === "unauthenticated") {
    redirect("/sign-in?callbackUrl=%2Faccount%2Fpreferences");
  }

  verifyProtectedFormToken(formData, {
    scope: PROTECTED_FORM_SCOPES.accountTelegramDisconnect,
    userId: session!.user.id,
  });

  await getRequiredDatabase().telegramConnection.updateMany({
    where: {
      userId: session!.user.id,
      disabledAt: null,
    },
    data: {
      disabledAt: new Date(),
      verificationCodeHash: null,
      verifiedAt: null,
    },
  });

  revalidatePath("/account/preferences");
}

function discordStatusRedirect(status: string): never {
  redirect(`/account/preferences?discordStatus=${encodeURIComponent(status)}`);
}

export async function connectDiscordWebhook(formData: FormData) {
  const session = await auth();
  if (authorizeRoute(session) === "unauthenticated") {
    redirect("/sign-in?callbackUrl=%2Faccount%2Fpreferences");
  }

  verifyProtectedFormToken(formData, {
    scope: PROTECTED_FORM_SCOPES.accountDiscordConnect,
    userId: session!.user.id,
  });

  const snapshot = await loadAccountSnapshot(session!.user);
  if (!snapshot.entitlements.channels.includes(AlertChannel.DISCORD)) {
    discordStatusRedirect("plan_required");
  }

  const webhookUrl = formData.get("discordWebhookUrl");
  if (typeof webhookUrl !== "string" || !webhookUrl.trim()) {
    discordStatusRedirect("missing_url");
  }

  let parsed: ReturnType<typeof parseDiscordWebhookUrl>;
  try {
    parsed = parseDiscordWebhookUrl(webhookUrl);
  } catch {
    discordStatusRedirect("invalid_url");
  }

  const database = getRequiredDatabase();
  const duplicate = await database.discordConnection.findFirst({
    where: {
      webhookId: parsed.webhookId,
      disabledAt: null,
      NOT: { userId: session!.user.id },
    },
    select: { id: true },
  });
  if (duplicate) {
    discordStatusRedirect("already_connected");
  }

  try {
    await sendDiscordWebhookTest(parsed);
  } catch (error) {
    if (error instanceof DiscordConnectionError) {
      discordStatusRedirect("test_failed");
    }
    throw error;
  }

  const encryptedWebhookToken = encryptDiscordWebhookToken({
    token: parsed.token,
  });
  const existing = await database.discordConnection.findFirst({
    where: { userId: session!.user.id },
    orderBy: { updatedAt: "desc" },
  });
  const data = {
    discordUserId: null,
    webhookId: parsed.webhookId,
    guildId: null,
    channelId: null,
    encryptedWebhookToken,
    verifiedAt: new Date(),
    disabledAt: null,
  };

  if (existing) {
    await database.discordConnection.update({
      where: { id: existing.id },
      data,
    });
  } else {
    await database.discordConnection.create({
      data: {
        userId: session!.user.id,
        ...data,
      },
    });
  }

  revalidatePath("/account/preferences");
  discordStatusRedirect("connected");
}

export async function disconnectDiscordWebhook(formData: FormData) {
  const session = await auth();
  if (authorizeRoute(session) === "unauthenticated") {
    redirect("/sign-in?callbackUrl=%2Faccount%2Fpreferences");
  }

  verifyProtectedFormToken(formData, {
    scope: PROTECTED_FORM_SCOPES.accountDiscordDisconnect,
    userId: session!.user.id,
  });

  await getRequiredDatabase().discordConnection.updateMany({
    where: {
      userId: session!.user.id,
      disabledAt: null,
    },
    data: {
      disabledAt: new Date(),
      encryptedWebhookToken: null,
      verifiedAt: null,
    },
  });

  revalidatePath("/account/preferences");
  discordStatusRedirect("disconnected");
}
