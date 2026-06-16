import { describe, expect, it } from "vitest";

import {
  createProtectedFormToken,
  PROTECTED_FORM_TOKEN_FIELD,
  verifyProtectedFormToken,
} from "@/lib/protected-form";

const secret = "0123456789abcdef0123456789abcdef";

function formDataWithToken(token: string) {
  const formData = new FormData();
  formData.set(PROTECTED_FORM_TOKEN_FIELD, token);
  return formData;
}

describe("protected form tokens", () => {
  it("verifies an encrypted scoped token", () => {
    const token = createProtectedFormToken({
      scope: "account:preferences",
      userId: "user-1",
      now: 1_800_000_000_000,
      secret,
    });

    const payload = verifyProtectedFormToken(formDataWithToken(token), {
      scope: "account:preferences",
      userId: "user-1",
      now: 1_800_000_001_000,
      secret,
    });

    expect(payload.scope).toBe("account:preferences");
    expect(payload.userId).toBe("user-1");
  });

  it("rejects missing, expired, wrong-scope, and wrong-user tokens", () => {
    const token = createProtectedFormToken({
      scope: "admin:alert-review",
      userId: "admin-1",
      ttlSeconds: 60,
      now: 1_800_000_000_000,
      secret,
    });

    expect(() =>
      verifyProtectedFormToken(new FormData(), {
        scope: "admin:alert-review",
        userId: "admin-1",
        secret,
      }),
    ).toThrow("Missing protected form token");
    expect(() =>
      verifyProtectedFormToken(formDataWithToken(token), {
        scope: "account:preferences",
        userId: "admin-1",
        secret,
      }),
    ).toThrow("scope mismatch");
    expect(() =>
      verifyProtectedFormToken(formDataWithToken(token), {
        scope: "admin:alert-review",
        userId: "admin-2",
        secret,
      }),
    ).toThrow("user mismatch");
    expect(() =>
      verifyProtectedFormToken(formDataWithToken(token), {
        scope: "admin:alert-review",
        userId: "admin-1",
        now: 1_800_000_061_000,
        secret,
      }),
    ).toThrow("expired");
  });

  it("rejects tampered ciphertext", () => {
    const token = createProtectedFormToken({
      scope: "sign-in:magic-link",
      secret,
    });
    const tampered = `${token.slice(0, -1)}${token.endsWith("a") ? "b" : "a"}`;

    expect(() =>
      verifyProtectedFormToken(formDataWithToken(tampered), {
        scope: "sign-in:magic-link",
        secret,
      }),
    ).toThrow();
  });
});
