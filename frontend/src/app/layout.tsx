import type { Metadata, Viewport } from "next";

import { SessionProvider } from "@/data/session";
import { NL2SQL_FONT_CLASS } from "@/lib/fonts";
import CrossHostRedirect from "@/platform/components/CrossHostRedirect";
import { ReactQueryClientProvider } from "@/platform/components/ReactQueryClientProvider";
import { ToastProvider } from "@/platform/components/ToastContext";

import "./globals.css";

export const metadata: Metadata = {
  title:
    "Database Agent by FutureSmart AI | Ask your database questions in plain English",
  description:
    "Connect a database and get an agent that answers questions about it in plain English — with the SQL it ran, the rows it read and a chart, every time.",
  applicationName: "Database Agent by FutureSmart AI",
  // The app is not a landing page: futuresmart.ai/solutions/database-agent is.
  robots: "noindex, nofollow",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#ffffff",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      {/* The design artifact's three faces — Plus Jakarta Sans for headings,
          Manrope for body copy, JetBrains Mono for SQL and ids. `theme.css`
          binds them to `font-family` inside the product's `n2s-root` scope. */}
      <body className={`${NL2SQL_FONT_CLASS} antialiased`}>
        {/* Sends a route this host does not own to the one that does — the
            edge function cannot see a client-side navigation. */}
        <CrossHostRedirect />
        {/* Same query client, toast surface and session source as the agent UI:
            every view below reads live data through them. */}
        <ReactQueryClientProvider>
          <ToastProvider>
            <SessionProvider>{children}</SessionProvider>
          </ToastProvider>
        </ReactQueryClientProvider>
      </body>
    </html>
  );
}
