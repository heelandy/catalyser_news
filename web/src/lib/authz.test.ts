import { describe, expect, it } from "vitest";

import { UserRole } from "@/generated/prisma/enums";
import {
  authorizeRoute,
  canAccessOwnedResource,
  hasMinimumRole,
  safeInternalRedirect,
} from "@/lib/authz";

function session(
  userId: string,
  role: (typeof UserRole)[keyof typeof UserRole],
) {
  return {
    user: { id: userId, role, email: `${userId}@example.com` },
    expires: "2099-01-01T00:00:00.000Z",
  };
}

describe("server authorization", () => {
  it("enforces the role hierarchy", () => {
    expect(hasMinimumRole(UserRole.ADMIN, UserRole.PAID_SUBSCRIBER)).toBe(true);
    expect(hasMinimumRole(UserRole.FREE_USER, UserRole.PAID_SUBSCRIBER)).toBe(
      false,
    );
  });

  it("protects admin routes from anonymous and non-admin users", () => {
    expect(authorizeRoute(null, UserRole.ADMIN)).toBe("unauthenticated");
    expect(
      authorizeRoute(session("free", UserRole.FREE_USER), UserRole.ADMIN),
    ).toBe("forbidden");
    expect(
      authorizeRoute(session("admin", UserRole.ADMIN), UserRole.ADMIN),
    ).toBe("allowed");
  });

  it("prevents IDOR access while allowing administrators", () => {
    expect(
      canAccessOwnedResource(session("u1", UserRole.FREE_USER), "u2"),
    ).toBe(false);
    expect(
      canAccessOwnedResource(session("u1", UserRole.FREE_USER), "u1"),
    ).toBe(true);
    expect(canAccessOwnedResource(session("a1", UserRole.ADMIN), "u2")).toBe(
      true,
    );
  });

  it("rejects external callback redirects", () => {
    expect(safeInternalRedirect("/account/preferences")).toBe(
      "/account/preferences",
    );
    expect(safeInternalRedirect("/account/preferences?tab=alerts")).toBe(
      "/account/preferences?tab=alerts",
    );
    expect(safeInternalRedirect("//attacker.example")).toBe("/");
    expect(safeInternalRedirect("https://attacker.example")).toBe("/");
    expect(safeInternalRedirect("/\\attacker")).toBe("/");
    expect(safeInternalRedirect("/%2Fattacker")).toBe("/");
    expect(safeInternalRedirect("/api/billing/checkout")).toBe("/");
    expect(safeInternalRedirect("/_next/static/chunk.js")).toBe("/");
  });
});
