import { chromium } from "playwright-core";

const baseUrl = process.env.APP_BASE_URL ?? "http://127.0.0.1:3000";
const browser = await chromium.launch({
  executablePath:
    process.env.EDGE_PATH ??
    "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  headless: true,
});

try {
  const page = await browser.newPage({
    viewport: { width: 1280, height: 900 },
  });

  await page.goto(`${baseUrl}/sign-in`, { waitUntil: "networkidle" });
  await page.getByRole("heading", { name: "Sign in by email" }).waitFor();
  await page.screenshot({ path: "foundation-auth.png", fullPage: true });

  await page.goto(`${baseUrl}/admin`, { waitUntil: "networkidle" });
  if (!page.url().includes("/sign-in?callbackUrl=")) {
    throw new Error(
      `Expected admin redirect to sign-in, received ${page.url()}`,
    );
  }

  await page.goto(`${baseUrl}/account/preferences`, {
    waitUntil: "networkidle",
  });
  if (!page.url().includes("/sign-in?callbackUrl=")) {
    throw new Error(
      `Expected preferences redirect to sign-in, received ${page.url()}`,
    );
  }

  console.log("Auth route verification passed.");
} finally {
  await browser.close();
}
