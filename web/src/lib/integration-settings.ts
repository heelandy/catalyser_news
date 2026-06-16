import "server-only";

import {
  createCipheriv,
  createDecipheriv,
  createHash,
  randomBytes,
} from "node:crypto";

import {
  IntegrationProvider,
  IntegrationStatus,
} from "@/generated/prisma/enums";
import type { Prisma, PrismaClient } from "@/generated/prisma/client";
import { getServerEnv } from "@/lib/env";

export type IntegrationField = {
  key: string;
  label: string;
  kind: "public" | "secret";
  required: boolean;
  placeholder: string;
  help: string;
};

export type IntegrationDefinition = {
  provider: IntegrationProvider;
  displayName: string;
  description: string;
  fields: IntegrationField[];
};

export type IntegrationCard = IntegrationDefinition & {
  id: string | null;
  enabled: boolean;
  status: IntegrationStatus;
  source: "managed" | "environment" | "missing";
  publicValues: Record<string, string>;
  maskedSecrets: Record<string, string>;
  lastTestStatus: IntegrationStatus | null;
  lastTestMessage: string | null;
  lastTestedAt: Date | null;
  updatedAt: Date | null;
  tests: {
    id: string;
    status: IntegrationStatus;
    message: string;
    createdAt: Date;
  }[];
  missingRequiredKeys: string[];
};

export const INTEGRATION_DEFINITIONS: IntegrationDefinition[] = [
  {
    provider: IntegrationProvider.RESEND_EMAIL,
    displayName: "Resend email",
    description: "Magic links, subscriber email alerts, and delivery queue email.",
    fields: [
      {
        key: "AUTH_EMAIL_FROM",
        label: "Verified sender",
        kind: "public",
        required: true,
        placeholder: "Market Catalyst <alerts@your-domain.com>",
        help: "Sender must be verified in Resend before live delivery.",
      },
      {
        key: "RESEND_API_KEY",
        label: "Resend API key",
        kind: "secret",
        required: true,
        placeholder: "re_...",
        help: "Stored encrypted and shown only as a mask after save.",
      },
    ],
  },
  {
    provider: IntegrationProvider.TELEGRAM,
    displayName: "Telegram bot",
    description: "Telegram subscriber verification and alert delivery.",
    fields: [
      {
        key: "TELEGRAM_BOT_USERNAME",
        label: "Bot username",
        kind: "public",
        required: false,
        placeholder: "MarketCatalystBot",
        help: "Used in setup instructions shown to subscribers.",
      },
      {
        key: "TELEGRAM_WEBHOOK_URL",
        label: "Webhook URL",
        kind: "public",
        required: true,
        placeholder: "https://your-domain.com/api/integrations/telegram/webhook",
        help: "Public HTTPS endpoint registered with Telegram.",
      },
      {
        key: "TELEGRAM_BOT_TOKEN",
        label: "Bot token",
        kind: "secret",
        required: true,
        placeholder: "123456:ABC...",
        help: "Telegram Bot API token.",
      },
      {
        key: "TELEGRAM_WEBHOOK_SECRET",
        label: "Webhook secret",
        kind: "secret",
        required: true,
        placeholder: "32+ character secret",
        help: "Compared against Telegram's secret-token webhook header.",
      },
    ],
  },
  {
    provider: IntegrationProvider.DISCORD,
    displayName: "Discord platform",
    description: "Discord webhook encryption and subscriber Discord delivery.",
    fields: [
      {
        key: "DISCORD_WEBHOOK_SECRET",
        label: "Discord encryption secret",
        kind: "secret",
        required: true,
        placeholder: "32+ character secret",
        help: "Used to encrypt subscriber webhook tokens at rest.",
      },
    ],
  },
  {
    provider: IntegrationProvider.STRIPE,
    displayName: "Stripe billing",
    description: "Checkout, Customer Portal, catalog sync, and webhook processing.",
    fields: [
      {
        key: "STRIPE_WEBHOOK_URL",
        label: "Webhook URL",
        kind: "public",
        required: true,
        placeholder: "https://your-domain.com/api/stripe/webhook",
        help: "Endpoint configured in Stripe Dashboard.",
      },
      {
        key: "STRIPE_SECRET_KEY",
        label: "Secret key",
        kind: "secret",
        required: true,
        placeholder: "sk_test_...",
        help: "Stripe server-side API key.",
      },
      {
        key: "STRIPE_WEBHOOK_SECRET",
        label: "Webhook signing secret",
        kind: "secret",
        required: true,
        placeholder: "whsec_...",
        help: "Verifies Stripe webhook signatures.",
      },
    ],
  },
  {
    provider: IntegrationProvider.ENGINE_INGEST,
    displayName: "Python engine ingest",
    description: "Signed Python engine to web application alert ingestion.",
    fields: [
      {
        key: "CATALYST_ENGINE_ROOT",
        label: "Engine root",
        kind: "public",
        required: false,
        placeholder: "C:\\path\\to\\python nq Catalyst",
        help: "Local path used by operator tools.",
      },
      {
        key: "ENGINE_INGEST_URL",
        label: "Ingest URL",
        kind: "public",
        required: true,
        placeholder: "https://your-domain.com/api/engine/alerts",
        help: "Endpoint used by macro_web_ingest.py.",
      },
      {
        key: "ENGINE_INGEST_SECRET",
        label: "Ingest secret",
        kind: "secret",
        required: true,
        placeholder: "32+ character HMAC secret",
        help: "HMAC secret shared by Python sender and Next.js API.",
      },
    ],
  },
];

type ExistingSetting = {
  publicConfig: Prisma.JsonValue | null;
  encryptedSecrets: Prisma.JsonValue | null;
  maskedSecrets: Prisma.JsonValue | null;
};

function asRecord(value: Prisma.JsonValue | null | undefined) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return {} as Record<string, string>;
  }
  const out: Record<string, string> = {};
  for (const [key, candidate] of Object.entries(value)) {
    if (typeof candidate === "string") out[key] = candidate;
  }
  return out;
}

function integrationSecret(explicitSecret?: string) {
  const env = getServerEnv();
  const secret = explicitSecret ?? env.AUTH_SECRET ?? env.ENGINE_INGEST_SECRET;
  if (!secret || secret.length < 32) {
    throw new Error("A 32+ character secret is required for integration settings.");
  }
  return secret;
}

function encryptionKey(secret: string) {
  return createHash("sha256").update(secret).digest();
}

function encode(value: Buffer) {
  return value.toString("base64url");
}

function decode(value: string) {
  return Buffer.from(value, "base64url");
}

export function encryptIntegrationSecret(value: string, secret?: string) {
  const iv = randomBytes(12);
  const cipher = createCipheriv(
    "aes-256-gcm",
    encryptionKey(integrationSecret(secret)),
    iv,
  );
  const encrypted = Buffer.concat([
    cipher.update(value, "utf-8"),
    cipher.final(),
  ]);
  return `v1.${encode(iv)}.${encode(cipher.getAuthTag())}.${encode(encrypted)}`;
}

export function decryptIntegrationSecret(value: string, secret?: string) {
  const [version, ivText, tagText, encryptedText] = value.split(".");
  if (version !== "v1" || !ivText || !tagText || !encryptedText) {
    throw new Error("Invalid encrypted integration secret.");
  }
  const decipher = createDecipheriv(
    "aes-256-gcm",
    encryptionKey(integrationSecret(secret)),
    decode(ivText),
  );
  decipher.setAuthTag(decode(tagText));
  return Buffer.concat([
    decipher.update(decode(encryptedText)),
    decipher.final(),
  ]).toString("utf-8");
}

export function maskSecret(value: string) {
  const trimmed = value.trim();
  if (!trimmed) return "";
  if (trimmed.length <= 8) return "****";
  return `${trimmed.slice(0, 4)}...${trimmed.slice(-4)}`;
}

export function definitionForProvider(provider: IntegrationProvider) {
  const definition = INTEGRATION_DEFINITIONS.find(
    (item) => item.provider === provider,
  );
  if (!definition) throw new Error(`Unsupported integration provider: ${provider}`);
  return definition;
}

export function parseIntegrationProvider(value: FormDataEntryValue | null) {
  if (typeof value !== "string") throw new Error("Missing integration provider.");
  const provider = INTEGRATION_DEFINITIONS.find(
    (definition) => definition.provider === value,
  )?.provider;
  if (!provider) throw new Error("Unsupported integration provider.");
  return provider;
}

function envValue(key: string) {
  const env = getServerEnv() as Record<string, string | undefined>;
  if (key === "ENGINE_INGEST_URL") {
    const baseUrl = env.APP_BASE_URL;
    return baseUrl ? `${baseUrl.replace(/\/$/, "")}/api/engine/alerts` : "";
  }
  if (key === "TELEGRAM_WEBHOOK_URL") {
    const baseUrl = env.APP_BASE_URL;
    return baseUrl
      ? `${baseUrl.replace(/\/$/, "")}/api/integrations/telegram/webhook`
      : "";
  }
  if (key === "STRIPE_WEBHOOK_URL") {
    const baseUrl = env.APP_BASE_URL;
    return baseUrl ? `${baseUrl.replace(/\/$/, "")}/api/stripe/webhook` : "";
  }
  return env[key] ?? "";
}

function missingRequiredKeys(
  definition: IntegrationDefinition,
  publicValues: Record<string, string>,
  maskedSecrets: Record<string, string>,
) {
  return definition.fields
    .filter((field) => {
      if (!field.required) return false;
      if (field.kind === "public") return !publicValues[field.key]?.trim();
      return !maskedSecrets[field.key]?.trim();
    })
    .map((field) => field.key);
}

export function evaluateIntegrationStatus({
  definition,
  enabled,
  publicValues,
  maskedSecrets,
}: {
  definition: IntegrationDefinition;
  enabled: boolean;
  publicValues: Record<string, string>;
  maskedSecrets: Record<string, string>;
}) {
  if (!enabled) return IntegrationStatus.DISABLED;
  return missingRequiredKeys(definition, publicValues, maskedSecrets).length
    ? IntegrationStatus.NEEDS_ATTENTION
    : IntegrationStatus.CONFIGURED;
}

export function buildIntegrationSettingUpdate({
  provider,
  formData,
  existing,
}: {
  provider: IntegrationProvider;
  formData: FormData;
  existing: ExistingSetting | null;
}) {
  const definition = definitionForProvider(provider);
  const publicConfig = asRecord(existing?.publicConfig);
  const encryptedSecrets = asRecord(existing?.encryptedSecrets);
  const maskedSecrets = asRecord(existing?.maskedSecrets);
  const changedSecretKeys: string[] = [];

  for (const field of definition.fields) {
    if (field.kind === "public") {
      const value = formData.get(`public:${field.key}`);
      publicConfig[field.key] = typeof value === "string" ? value.trim() : "";
      continue;
    }
    const value = formData.get(`secret:${field.key}`);
    if (typeof value === "string" && value.trim()) {
      const trimmed = value.trim();
      encryptedSecrets[field.key] = encryptIntegrationSecret(trimmed);
      maskedSecrets[field.key] = maskSecret(trimmed);
      changedSecretKeys.push(field.key);
    }
  }

  const enabled = formData.get("enabled") === "on";
  const status = evaluateIntegrationStatus({
    definition,
    enabled,
    publicValues: publicConfig,
    maskedSecrets,
  });

  return {
    data: {
      provider,
      displayName: definition.displayName,
      enabled,
      publicConfig,
      encryptedSecrets,
      maskedSecrets,
      status,
      ...(changedSecretKeys.length ? { lastRotatedAt: new Date() } : {}),
    },
    changedSecretKeys,
    missingRequiredKeys: missingRequiredKeys(
      definition,
      publicConfig,
      maskedSecrets,
    ),
  };
}

export async function loadIntegrationCards(database: PrismaClient) {
  const settings = await database.integrationSetting.findMany({
    include: {
      tests: {
        orderBy: { createdAt: "desc" },
        take: 3,
      },
    },
    orderBy: { provider: "asc" },
  });
  const byProvider = new Map(settings.map((setting) => [setting.provider, setting]));

  return INTEGRATION_DEFINITIONS.map((definition): IntegrationCard => {
    const setting = byProvider.get(definition.provider);
    const publicValues = asRecord(setting?.publicConfig);
    const maskedSecrets = asRecord(setting?.maskedSecrets);
    let envHasRequired = true;

    for (const field of definition.fields) {
      if (field.kind === "public" && !publicValues[field.key]) {
        publicValues[field.key] = envValue(field.key);
      }
      if (field.kind === "secret" && !maskedSecrets[field.key]) {
        const value = envValue(field.key);
        if (value) maskedSecrets[field.key] = maskSecret(value);
      }
      if (field.required) {
        const present =
          field.kind === "public"
            ? Boolean(envValue(field.key) || publicValues[field.key])
            : Boolean(envValue(field.key) || maskedSecrets[field.key]);
        envHasRequired &&= present;
      }
    }

    const status =
      setting?.status ??
      (envHasRequired
        ? IntegrationStatus.CONFIGURED
        : IntegrationStatus.NOT_CONFIGURED);
    const missing = missingRequiredKeys(definition, publicValues, maskedSecrets);

    return {
      ...definition,
      id: setting?.id ?? null,
      enabled: setting?.enabled ?? envHasRequired,
      status,
      source: setting ? "managed" : envHasRequired ? "environment" : "missing",
      publicValues,
      maskedSecrets,
      lastTestStatus: setting?.lastTestStatus ?? null,
      lastTestMessage: setting?.lastTestMessage ?? null,
      lastTestedAt: setting?.lastTestedAt ?? null,
      updatedAt: setting?.updatedAt ?? null,
      tests:
        setting?.tests.map((test) => ({
          id: test.id,
          status: test.status,
          message: test.message,
          createdAt: test.createdAt,
        })) ?? [],
      missingRequiredKeys: missing,
    };
  });
}

export function localIntegrationTest(card: IntegrationCard) {
  if (!card.enabled) {
    return {
      status: IntegrationStatus.DISABLED,
      message: "Integration is disabled.",
    };
  }
  if (card.missingRequiredKeys.length) {
    return {
      status: IntegrationStatus.ERROR,
      message: `Missing required setting(s): ${card.missingRequiredKeys.join(", ")}.`,
    };
  }
  return {
    status: IntegrationStatus.VERIFIED,
    message:
      "Local configuration is complete. Run the provider's live sandbox test before production use.",
  };
}
