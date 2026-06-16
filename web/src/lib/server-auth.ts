import "server-only";

import { redirect } from "next/navigation";

import { auth } from "@/auth";
import {
  UserRole,
  type UserRole as UserRoleValue,
} from "@/generated/prisma/enums";
import { authorizeRoute } from "@/lib/authz";

export async function requireUser(callbackUrl: string) {
  const session = await auth();
  if (authorizeRoute(session) === "unauthenticated") {
    redirect(`/sign-in?callbackUrl=${encodeURIComponent(callbackUrl)}`);
  }
  return session!.user;
}

export async function requireRole(
  requiredRole: UserRoleValue,
  callbackUrl: string,
) {
  const session = await auth();
  const decision = authorizeRoute(session, requiredRole);
  if (decision === "unauthenticated") {
    redirect(`/sign-in?callbackUrl=${encodeURIComponent(callbackUrl)}`);
  }
  if (decision === "forbidden") {
    redirect("/forbidden");
  }
  return session!.user;
}

export async function requireAdmin() {
  return requireRole(UserRole.ADMIN, "/admin");
}
