"use client";

import { useEffect, useRef, type ReactNode } from "react";

import { signIn, useSession } from "@/data/session";
import Loading from "@/platform/components/loading";

/**
 * Protects the NL2SQL workspace in both mounts.
 *
 * The product is statically exported, so this client-side profile check is the
 * first point at which its auth cookie can be verified. It renders the agent
 * UI's own loading skeleton, so arriving here from that dashboard shows one
 * continuous loading state rather than two different ones.
 *
 * The agent UI carries its own copy of this gate at
 * `src/app/database-agent/RequireSession.tsx` for the mounted build; this one covers
 * the standalone app, which has no dashboard chrome above it to gate.
 */
export default function RequireSession({ children }: { children: ReactNode }) {
  const { profile, isLoading, isSignedOut } = useSession();
  const redirectStarted = useRef(false);

  useEffect(() => {
    if (!isSignedOut || redirectStarted.current) return;
    redirectStarted.current = true;
    signIn();
  }, [isSignedOut]);

  if (isLoading || !profile) {
    return <Loading message="Signing you in…" />;
  }

  return <>{children}</>;
}
