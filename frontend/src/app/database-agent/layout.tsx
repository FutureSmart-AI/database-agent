"use client";

import RequireSession from "@/components/shell/RequireSession";

/**
 * Everything under `/database-agent` needs a session — the product has no public page of
 * its own any more, so this layout gates the whole tree. Providers themselves
 * are in the root layout: this app is nothing but this product, so they wrap
 * everything.
 */
export default function DatabaseAgentLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return <RequireSession>{children}</RequireSession>;
}
