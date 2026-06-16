"use server";

import { signIn } from "@/auth";
import { safeInternalRedirect } from "@/lib/authz";
import {
  PROTECTED_FORM_SCOPES,
  verifyProtectedFormToken,
} from "@/lib/protected-form";

export async function requestMagicLink(formData: FormData) {
  verifyProtectedFormToken(formData, {
    scope: PROTECTED_FORM_SCOPES.magicLink,
  });

  const email = formData.get("email");
  if (typeof email !== "string" || !email.includes("@")) {
    throw new Error("Enter a valid email address.");
  }

  await signIn("resend", {
    email: email.trim().toLowerCase(),
    redirectTo: safeInternalRedirect(formData.get("callbackUrl")),
  });
}
