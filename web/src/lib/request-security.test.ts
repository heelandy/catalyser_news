import { describe, expect, it } from "vitest";

import {
  isSameOriginRequest,
  rejectCrossOriginRequest,
} from "@/lib/request-security";

describe("request security", () => {
  it("allows missing or same-origin origin headers", () => {
    expect(
      isSameOriginRequest(
        new Request("http://localhost:3000/api/billing/checkout"),
        "http://localhost:3000",
      ),
    ).toBe(true);
    expect(
      isSameOriginRequest(
        new Request("http://localhost:3000/api/billing/checkout", {
          headers: { origin: "http://localhost:3000" },
        }),
        "http://localhost:3000",
      ),
    ).toBe(true);
  });

  it("rejects cross-origin billing requests", () => {
    const request = new Request("http://localhost:3000/api/billing/checkout", {
      method: "POST",
      headers: { origin: "https://attacker.example" },
    });

    expect(isSameOriginRequest(request, "http://localhost:3000")).toBe(false);
    expect(
      rejectCrossOriginRequest(request, "http://localhost:3000")?.status,
    ).toBe(403);
  });
});
