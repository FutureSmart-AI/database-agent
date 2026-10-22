"use client";

import { createContext, useContext, type ReactNode } from "react";
import { usePathname } from "next/navigation";

import { useQuery } from "@tanstack/react-query";

import { fetchProfile } from "@/platform/components/rag/dashboard/auth-apis";
import { authLoginUrlFor, standaloneAuth } from "@/platform/config";

/** The signed-in user, as returned by the auth service's `GET /user/me`. */
export interface Profile {
  email: string;
  name?: string;
  [key: string]: unknown;
}

interface SessionValue {
  profile: Profile | null;
  isLoading: boolean;
  /** True once the profile request failed — the session is gone. */
  isSignedOut: boolean;
}

const SessionContext = createContext<SessionValue>({
  profile: null,
  isLoading: true,
  isSignedOut: false,
});

/**
 * The signed-in user for the whole app.
 *
 * Every request in `src/data` is scoped by `owner_id`, which is this profile's
 * email — so the app has no data at all until this resolves. The token itself
 * lives in an httpOnly cookie set by the auth service; the browser attaches it,
 * and a 401 anywhere means the session is over.
 */
export function SessionProvider({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { data, isLoading, isError } = useQuery({
    enabled: !(standaloneAuth && pathname.startsWith("/standalone-login")),
    queryKey: ["profile"],
    queryFn: fetchProfile,
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: 5 * 60 * 1000,
  });

  return (
    <SessionContext.Provider
      value={{
        profile: (data as Profile) ?? null,
        isLoading,
        isSignedOut: isError,
      }}
    >
      {children}
    </SessionContext.Provider>
  );
}

export function useSession(): SessionValue {
  return useContext(SessionContext);
}

/**
 * The signed-in user's email, which every API call uses as `owner_id`.
 * Returns `undefined` while the profile is still loading, so queries can stay
 * disabled rather than firing an unscoped request.
 */
export function useOwnerId(): string | undefined {
  return useSession().profile?.email;
}

/** Sends the browser to SSO, returning here afterwards. */
export function signIn(): void {
  window.location.assign(authLoginUrlFor(window.location.href));
}
