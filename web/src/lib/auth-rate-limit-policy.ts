const WINDOW_MS = 15 * 60 * 1000;
const BLOCK_MS = 30 * 60 * 1000;
const MAX_ATTEMPTS = 5;

export type AuthRateLimitState = {
  attempts: number;
  windowStartedAt: Date;
  blockedUntil: Date | null;
};

export type AuthRateLimitDecision = {
  allowed: boolean;
  nextState: AuthRateLimitState;
  retryAfterSeconds: number;
};

export function evaluateAuthRateLimit(
  state: AuthRateLimitState | null,
  now: Date,
): AuthRateLimitDecision {
  if (state?.blockedUntil && state.blockedUntil.getTime() > now.getTime()) {
    return {
      allowed: false,
      nextState: state,
      retryAfterSeconds: Math.ceil(
        (state.blockedUntil.getTime() - now.getTime()) / 1000,
      ),
    };
  }

  const windowExpired =
    !state || now.getTime() - state.windowStartedAt.getTime() >= WINDOW_MS;
  const attempts = windowExpired ? 1 : state.attempts + 1;

  if (attempts > MAX_ATTEMPTS) {
    const blockedUntil = new Date(now.getTime() + BLOCK_MS);
    return {
      allowed: false,
      nextState: {
        attempts,
        windowStartedAt: windowExpired ? now : state.windowStartedAt,
        blockedUntil,
      },
      retryAfterSeconds: BLOCK_MS / 1000,
    };
  }

  return {
    allowed: true,
    nextState: {
      attempts,
      windowStartedAt: windowExpired ? now : state.windowStartedAt,
      blockedUntil: null,
    },
    retryAfterSeconds: 0,
  };
}
