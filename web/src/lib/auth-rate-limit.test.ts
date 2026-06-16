import { describe, expect, it } from "vitest";

import { evaluateAuthRateLimit } from "@/lib/auth-rate-limit-policy";

describe("authentication rate limiting", () => {
  it("allows five requests in a fifteen-minute window", () => {
    const now = new Date("2026-06-15T14:00:00.000Z");
    let state = null;

    for (let attempt = 1; attempt <= 5; attempt += 1) {
      const decision = evaluateAuthRateLimit(state, now);
      expect(decision.allowed).toBe(true);
      state = decision.nextState;
    }
  });

  it("blocks the sixth request for thirty minutes", () => {
    const now = new Date("2026-06-15T14:00:00.000Z");
    const decision = evaluateAuthRateLimit(
      { attempts: 5, windowStartedAt: now, blockedUntil: null },
      now,
    );

    expect(decision.allowed).toBe(false);
    expect(decision.retryAfterSeconds).toBe(1800);
  });

  it("starts a fresh window after fifteen minutes", () => {
    const decision = evaluateAuthRateLimit(
      {
        attempts: 5,
        windowStartedAt: new Date("2026-06-15T14:00:00.000Z"),
        blockedUntil: null,
      },
      new Date("2026-06-15T14:15:00.000Z"),
    );

    expect(decision.allowed).toBe(true);
    expect(decision.nextState.attempts).toBe(1);
  });
});
