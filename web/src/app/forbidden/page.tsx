import { ShieldX } from "lucide-react";
import Link from "next/link";

export default function ForbiddenPage() {
  return (
    <main className="access-shell">
      <section className="access-panel" aria-labelledby="forbidden-title">
        <div className="access-icon danger">
          <ShieldX size={24} />
        </div>
        <p className="eyebrow">Access denied</p>
        <h1 id="forbidden-title">Your account cannot open this route</h1>
        <p>The server checked your current role before returning this page.</p>
        <Link className="access-link" href="/">
          Return to overview
        </Link>
      </section>
    </main>
  );
}
