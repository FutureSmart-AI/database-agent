"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { APP, LEGACY_APP } from "@/lib/routes";

/**
 * Forwards the product's retired URLs to their current home.
 *
 * Two renames left URLs behind. The `/dashboard` segment was dropped when the
 * marketing page above it went away and the workspace became the product's entry
 * point; then the product itself was renamed from NL2SQL to Database Agent
 * (ClickUp 86bbh7h9z) and moved from `/nl2sql` to `/database-agent`. Bookmarks,
 * links pasted into tickets and the share URLs people have already sent out
 * still carry the old shapes, and the build is a static export — there is no
 * server to answer them with a 302 — so each retired path keeps a page whose
 * only job is this hop.
 *
 * Both rewrites happen here, so `/nl2sql/dashboard/share` lands on
 * `/database-agent/share` in one hop rather than bouncing through an
 * intermediate URL.
 *
 * The query string is read off `window.location` rather than through
 * `useSearchParams`, which would force every one of these stubs to carry a
 * Suspense boundary to prerender. `replace` keeps the dead URL out of the back
 * button.
 */
export default function LegacyPathRedirect() {
  const router = useRouter();

  useEffect(() => {
    const { pathname, search, hash } = window.location;
    let next = pathname;
    if (next === LEGACY_APP || next.startsWith(`${LEGACY_APP}/`)) {
      next = APP + next.slice(LEGACY_APP.length);
    }
    next = next.replace(`${APP}/dashboard`, APP);
    router.replace(next + search + hash);
  }, [router]);

  return null;
}
