import { PrismaAdapter } from "@auth/prisma-adapter";
import NextAuth from "next-auth";
import Resend from "next-auth/providers/resend";

import { UserRole } from "@/generated/prisma/enums";
import { enforceMagicLinkRateLimit } from "@/lib/auth-rate-limit";
import { getRequiredDatabase } from "@/lib/db";
import { getServerEnv } from "@/lib/env";
import { authorizeRoute } from "@/lib/authz";

const env = getServerEnv();
const database = getRequiredDatabase();
const emailAuthConfigured = Boolean(env.RESEND_API_KEY && env.AUTH_EMAIL_FROM);

function resendProvider() {
  const provider = Resend({
    apiKey: env.RESEND_API_KEY,
    from: env.AUTH_EMAIL_FROM,
    maxAge: 15 * 60,
  });
  const sendVerificationRequest = provider.sendVerificationRequest;

  return {
    ...provider,
    async sendVerificationRequest(
      params: Parameters<typeof sendVerificationRequest>[0],
    ) {
      await enforceMagicLinkRateLimit(params.identifier);
      await sendVerificationRequest(params);
    },
  };
}

export const authConfiguration = {
  emailAuthConfigured,
  sessionMaxAgeSeconds: 30 * 24 * 60 * 60,
};

export const { handlers, auth, signIn, signOut } = NextAuth({
  adapter: PrismaAdapter(database),
  secret: env.AUTH_SECRET,
  session: {
    strategy: "database",
    maxAge: authConfiguration.sessionMaxAgeSeconds,
    updateAge: 24 * 60 * 60,
  },
  providers: emailAuthConfigured ? [resendProvider()] : [],
  pages: {
    signIn: "/sign-in",
  },
  callbacks: {
    session({ session, user }) {
      session.user.id = user.id;
      session.user.role = user.role ?? UserRole.FREE_USER;
      return session;
    },
    authorized({ auth: session, request }) {
      const pathname = request.nextUrl.pathname;
      if (pathname.startsWith("/admin")) {
        return authorizeRoute(session, UserRole.ADMIN) === "allowed";
      }
      if (
        pathname.startsWith("/account/billing") ||
        pathname.startsWith("/account/preferences")
      ) {
        return authorizeRoute(session) === "allowed";
      }
      return true;
    },
  },
});
