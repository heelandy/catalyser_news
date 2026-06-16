"use client";

import { CreditCard, ExternalLink } from "lucide-react";
import { useState, useTransition } from "react";

type BillingInterval = "MONTHLY" | "QUARTERLY" | "ANNUAL";
type BillingActionProps =
  | {
      mode: "checkout";
      planCode: "basic" | "pro" | "elite";
      interval: BillingInterval;
      label: string;
    }
  | {
      mode: "portal";
      label: string;
    };

export function BillingActionButton(props: BillingActionProps) {
  const [message, setMessage] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  function submit() {
    setMessage(null);
    startTransition(async () => {
      const response = await fetch(
        props.mode === "portal"
          ? "/api/billing/portal"
          : "/api/billing/checkout",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body:
            props.mode === "checkout"
              ? JSON.stringify({
                  planCode: props.planCode,
                  interval: props.interval,
                })
              : undefined,
        },
      );
      const body = (await response.json()) as { url?: string; error?: string };
      if (!response.ok || !body.url) {
        setMessage(body.error ?? "Billing is not available yet.");
        return;
      }
      window.location.assign(body.url);
    });
  }

  const Icon = props.mode === "portal" ? ExternalLink : CreditCard;
  return (
    <div className="billing-action">
      <button type="button" onClick={submit} disabled={pending}>
        <Icon size={16} />
        <span>{pending ? "Opening..." : props.label}</span>
      </button>
      {message && <small role="status">{message}</small>}
    </div>
  );
}
