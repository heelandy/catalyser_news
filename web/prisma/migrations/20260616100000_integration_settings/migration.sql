-- CreateEnum
CREATE TYPE "IntegrationProvider" AS ENUM ('RESEND_EMAIL', 'TELEGRAM', 'DISCORD', 'STRIPE', 'ENGINE_INGEST');

-- CreateEnum
CREATE TYPE "IntegrationStatus" AS ENUM ('NOT_CONFIGURED', 'CONFIGURED', 'VERIFIED', 'NEEDS_ATTENTION', 'ERROR', 'DISABLED');

-- CreateTable
CREATE TABLE "IntegrationSetting" (
    "id" TEXT NOT NULL,
    "provider" "IntegrationProvider" NOT NULL,
    "enabled" BOOLEAN NOT NULL DEFAULT false,
    "displayName" VARCHAR(120) NOT NULL,
    "publicConfig" JSONB,
    "encryptedSecrets" JSONB,
    "maskedSecrets" JSONB,
    "status" "IntegrationStatus" NOT NULL DEFAULT 'NOT_CONFIGURED',
    "lastTestStatus" "IntegrationStatus",
    "lastTestMessage" TEXT,
    "lastTestedAt" TIMESTAMP(3),
    "lastRotatedAt" TIMESTAMP(3),
    "updatedById" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "IntegrationSetting_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "IntegrationTestLog" (
    "id" TEXT NOT NULL,
    "settingId" TEXT,
    "provider" "IntegrationProvider" NOT NULL,
    "status" "IntegrationStatus" NOT NULL,
    "message" TEXT NOT NULL,
    "actorUserId" TEXT,
    "metadata" JSONB,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "IntegrationTestLog_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "IntegrationSetting_provider_key" ON "IntegrationSetting"("provider");

-- CreateIndex
CREATE INDEX "IntegrationSetting_enabled_status_idx" ON "IntegrationSetting"("enabled", "status");

-- CreateIndex
CREATE INDEX "IntegrationSetting_updatedAt_idx" ON "IntegrationSetting"("updatedAt");

-- CreateIndex
CREATE INDEX "IntegrationTestLog_provider_createdAt_idx" ON "IntegrationTestLog"("provider", "createdAt");

-- CreateIndex
CREATE INDEX "IntegrationTestLog_status_createdAt_idx" ON "IntegrationTestLog"("status", "createdAt");

-- AddForeignKey
ALTER TABLE "IntegrationTestLog" ADD CONSTRAINT "IntegrationTestLog_settingId_fkey" FOREIGN KEY ("settingId") REFERENCES "IntegrationSetting"("id") ON DELETE SET NULL ON UPDATE CASCADE;
