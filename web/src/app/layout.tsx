import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Market Catalyst Alert System",
  description:
    "NQ-focused market catalyst monitoring and subscriber alert operations.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="min-h-full">{children}</body>
    </html>
  );
}
