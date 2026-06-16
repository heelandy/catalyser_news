import type { Session } from "next-auth";

import {
  UserRole,
  type UserRole as UserRoleValue,
} from "@/generated/prisma/enums";

const roleRank: Record<UserRoleValue, number> = {
  [UserRole.FREE_USER]: 0,
  [UserRole.PAID_SUBSCRIBER]: 1,
  [UserRole.ADMIN]: 2,
};

export function hasMinimumRole(actual: UserRoleValue, required: UserRoleValue) {
  return roleRank[actual] >= roleRank[required];
}

export function canAccessOwnedResource(
  session: Session | null,
  ownerUserId: string,
) {
  if (!session?.user?.id) return false;
  return (
    session.user.id === ownerUserId || session.user.role === UserRole.ADMIN
  );
}

export function authorizeRoute(
  session: Session | null,
  requiredRole: UserRoleValue = UserRole.FREE_USER,
) {
  if (!session?.user?.id) return "unauthenticated" as const;
  if (!hasMinimumRole(session.user.role, requiredRole)) {
    return "forbidden" as const;
  }
  return "allowed" as const;
}

export function safeInternalRedirect(value: FormDataEntryValue | null) {
  if (typeof value !== "string") return "/";
  const candidate = value.trim();
  if (
    !candidate.startsWith("/") ||
    candidate.startsWith("//") ||
    candidate.includes("\\") ||
    /[\u0000-\u001F\u007F]/.test(candidate) ||
    /%(2f|5c)/i.test(candidate)
  ) {
    return "/";
  }

  try {
    const parsed = new URL(candidate, "https://market-catalyst.local");
    if (parsed.origin !== "https://market-catalyst.local") return "/";
    if (
      parsed.pathname.startsWith("/api") ||
      parsed.pathname.startsWith("/_next")
    ) {
      return "/";
    }
    return `${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return "/";
  }
}
