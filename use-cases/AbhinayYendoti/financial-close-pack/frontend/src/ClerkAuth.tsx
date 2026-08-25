/**
 * Clerk wiring.
 *
 * Kept out of App.tsx so the workspace stays provider-agnostic and so the Clerk hooks are
 * only ever mounted when a publishable key exists - `useAuth` outside a `ClerkProvider`
 * throws, so the provider cannot simply be rendered unconditionally.
 *
 * The bridge does two jobs: it converts a Clerk session into the `Session` shape the app
 * already speaks, and it registers a token provider so every API request carries a fresh
 * token rather than one captured at sign-in.
 */

import { ClerkProvider, useAuth, useClerk, useUser } from "@clerk/clerk-react";
import { useEffect, useMemo, useState } from "react";

import { App, type AuthAdapter } from "./App";
import { setTokenProvider } from "./lib/api";
import type { Session } from "./lib/types";

function ClerkBridge() {
  const { isLoaded, isSignedIn, getToken, signOut } = useAuth();
  const { user } = useUser();
  const clerk = useClerk();
  const [token, setToken] = useState<string | null>(null);

  // `getToken()` serves a cached token, which is cheap but goes stale before Clerk
  // renews it. `skipCache` forces a real refresh; the api client asks for that only
  // after the server has rejected a token, so the common path stays cache-cheap.
  useEffect(() => {
    setTokenProvider((forceRefresh) => getToken(forceRefresh ? { skipCache: true } : undefined));
    return () => setTokenProvider(null);
  }, [getToken]);

  // The app gates its first load on a non-empty token, so seed one on sign-in.
  useEffect(() => {
    let cancelled = false;
    if (!isSignedIn) {
      setToken(null);
      return;
    }
    void getToken().then((next) => {
      if (!cancelled) setToken(next);
    });
    return () => {
      cancelled = true;
    };
  }, [isSignedIn, getToken]);

  const session: Session | null = useMemo(() => {
    if (!isSignedIn || !user || !token) return null;
    const name =
      user.fullName ||
      user.username ||
      user.primaryEmailAddress?.emailAddress ||
      user.id;
    // Sign-offs are attributed to this, so role comes from Clerk's public metadata when
    // an admin has set one rather than being invented here.
    const role = (user.publicMetadata?.role as string | undefined) || "Controller";
    return { token, user: { id: user.id, name, role } };
  }, [isSignedIn, user, token]);

  const auth: AuthAdapter = useMemo(
    () => ({
      session,
      signIn: () => void clerk.openSignIn({}),
      signOut: () => void signOut(),
    }),
    [session, clerk, signOut]
  );

  // Clerk resolves its session asynchronously. Rendering the app before that finishes
  // would flash the signed-out screen at an already-signed-in user.
  if (!isLoaded) return null;

  return <App auth={auth} />;
}

export function ClerkAuthedApp({ publishableKey }: { publishableKey: string }) {
  return (
    <ClerkProvider publishableKey={publishableKey} afterSignOutUrl="/">
      <ClerkBridge />
    </ClerkProvider>
  );
}
