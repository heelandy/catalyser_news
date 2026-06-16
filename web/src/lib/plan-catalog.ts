import {
  AlertChannel,
  BillingInterval,
  type Prisma,
} from "@/generated/prisma/client";

export const PLAN_CODES = ["free", "basic", "pro", "elite"] as const;

export type PlanCode = (typeof PLAN_CODES)[number];

export type PlanEntitlements = {
  accountAccess: boolean;
  summaryDelayMinutes: number;
  dailyAlertLimit: number | null;
  alertHistoryDays: number | null;
  channels: AlertChannel[];
  realtimeAlerts: boolean;
  fullAnalysis: boolean;
  preferences: boolean;
  priorityAlerts: boolean;
  nqPriority: boolean;
  premiumCommunity: boolean;
};

export type PlanDefinition = {
  code: PlanCode;
  name: string;
  description: string;
  priorityRank: number;
  prices: Record<BillingInterval, number>;
  entitlements: PlanEntitlements;
};

export const PLAN_CATALOG: Record<PlanCode, PlanDefinition> = {
  free: {
    code: "free",
    name: "Free",
    description: "Account access with delayed, limited market summaries.",
    priorityRank: 0,
    prices: {
      MONTHLY: 0,
      QUARTERLY: 0,
      ANNUAL: 0,
    },
    entitlements: {
      accountAccess: true,
      summaryDelayMinutes: 30,
      dailyAlertLimit: 0,
      alertHistoryDays: 1,
      channels: [],
      realtimeAlerts: false,
      fullAnalysis: false,
      preferences: false,
      priorityAlerts: false,
      nqPriority: false,
      premiumCommunity: false,
    },
  },
  basic: {
    code: "basic",
    name: "Basic",
    description: "Email catalyst alerts, a daily limit, and basic history.",
    priorityRank: 10,
    prices: {
      MONTHLY: 2900,
      QUARTERLY: 7900,
      ANNUAL: 29000,
    },
    entitlements: {
      accountAccess: true,
      summaryDelayMinutes: 5,
      dailyAlertLimit: 5,
      alertHistoryDays: 30,
      channels: [AlertChannel.EMAIL],
      realtimeAlerts: false,
      fullAnalysis: false,
      preferences: false,
      priorityAlerts: false,
      nqPriority: false,
      premiumCommunity: false,
    },
  },
  pro: {
    code: "pro",
    name: "Pro",
    description:
      "Real-time multi-channel alerts, full analysis, history, and preferences.",
    priorityRank: 20,
    prices: {
      MONTHLY: 7900,
      QUARTERLY: 21900,
      ANNUAL: 79000,
    },
    entitlements: {
      accountAccess: true,
      summaryDelayMinutes: 0,
      dailyAlertLimit: null,
      alertHistoryDays: null,
      channels: [
        AlertChannel.EMAIL,
        AlertChannel.TELEGRAM,
        AlertChannel.DISCORD,
      ],
      realtimeAlerts: true,
      fullAnalysis: true,
      preferences: true,
      priorityAlerts: false,
      nqPriority: false,
      premiumCommunity: false,
    },
  },
  elite: {
    code: "elite",
    name: "Elite",
    description:
      "Fastest NQ-priority alerts, full platform access, and premium community access.",
    priorityRank: 30,
    prices: {
      MONTHLY: 14900,
      QUARTERLY: 41900,
      ANNUAL: 149000,
    },
    entitlements: {
      accountAccess: true,
      summaryDelayMinutes: 0,
      dailyAlertLimit: null,
      alertHistoryDays: null,
      channels: [
        AlertChannel.EMAIL,
        AlertChannel.TELEGRAM,
        AlertChannel.DISCORD,
      ],
      realtimeAlerts: true,
      fullAnalysis: true,
      preferences: true,
      priorityAlerts: true,
      nqPriority: true,
      premiumCommunity: true,
    },
  },
};

export function isPlanCode(value: string): value is PlanCode {
  return PLAN_CODES.includes(value as PlanCode);
}

export function planFeaturesForDatabase(
  plan: PlanDefinition,
): Prisma.InputJsonValue {
  return {
    entitlementVersion: 1,
    ...plan.entitlements,
  };
}

export function publicPlanCatalog() {
  return PLAN_CODES.map((code) => PLAN_CATALOG[code]);
}
