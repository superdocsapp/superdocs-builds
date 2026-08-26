import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import {
  QueryClient,
  QueryClientProvider,
  useQueryClient,
} from '@tanstack/react-query';
import { ClerkProvider, useClerk, useUser } from '@clerk/react';
import { Loader2, PenLine } from 'lucide-react';
import { ErrorBoundary } from '@/components/error-boundary';
import { Button } from '@/components/ui/button';
import { Toaster } from '@/components/ui/toaster';
import { TooltipProvider } from '@/components/ui/tooltip';
import NotFound from '@/pages/not-found';
import {
  Redirect,
  Route,
  Switch,
  useLocation,
  Router as WouterRouter,
} from 'wouter';

import { LabProvider } from '@/lib/store';
import { PreferencesProvider } from '@/lib/preferences';
import {
  basePath,
  clerkAppearance,
  clerkProxyUrl,
  clerkPubKey,
  stripBase,
} from '@/lib/clerk';
import {
  createAuthenticatedPersistence,
  createAuthenticatedPreferencesPersistence,
  hasEnteredGuestSession,
  markGuestSessionEntered,
} from '@/lib/persistence';
import { AppShell } from '@/components/layout/AppShell';

import EditorPage from '@/pages/EditorPage';
import HistoryPage from '@/pages/HistoryPage';
import ConversationPage from '@/pages/ConversationPage';
import ComparePage from '@/pages/ComparePage';
import BenchmarkPage from '@/pages/BenchmarkPage';
import InsightsPage from '@/pages/InsightsPage';
import SettingsPage from '@/pages/SettingsPage';
import WelcomePage from '@/pages/WelcomePage';
import { SignInPage, SignUpPage } from '@/pages/AuthPages';

const queryClient = new QueryClient();

/** Minimal branded splash used while auth/preferences/workspace resolve. */
function BootScreen({ label }: { label?: string }) {
  return (
    <div
      className="flex min-h-svh flex-col items-center justify-center gap-3 bg-background"
      data-testid="screen-boot"
    >
      <span className="flex h-10 w-10 items-center justify-center rounded-md bg-primary text-primary-foreground">
        <PenLine className="h-5 w-5" />
      </span>
      <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
      {label ? <p className="text-sm text-muted-foreground">{label}</p> : null}
    </div>
  );
}

/** Full-page state while a signed-in user's workspace loads (or fails to). */
function WorkspaceGate({
  error,
  retry,
}: {
  error: string | null;
  retry: () => void;
}) {
  const { signOut } = useClerk();
  if (!error) return <BootScreen label="Loading your workspace…" />;
  return (
    <div
      className="flex min-h-svh flex-col items-center justify-center gap-4 bg-background px-6 text-center"
      data-testid="screen-workspace-error"
    >
      <p className="max-w-sm text-sm text-foreground">{error}</p>
      <div className="flex gap-2">
        <Button onClick={retry} data-testid="button-retry-workspace">
          Try again
        </Button>
        <Button
          variant="outline"
          onClick={() => signOut({ redirectUrl: basePath || '/' })}
          data-testid="button-workspace-sign-out"
        >
          Sign out
        </Button>
      </div>
    </div>
  );
}

// Helps the webview stay up-to-date when the signed-in user changes by
// invalidating the QueryClient cache.
function ClerkQueryClientCacheInvalidator() {
  const { addListener } = useClerk();
  const activeQueryClient = useQueryClient();
  const prevUserIdRef = useRef<string | null | undefined>(undefined);

  useEffect(() => {
    const unsubscribe = addListener(({ user }) => {
      const userId = user?.id ?? null;
      if (
        prevUserIdRef.current !== undefined &&
        prevUserIdRef.current !== userId
      ) {
        activeQueryClient.clear();
      }
      prevUserIdRef.current = userId;
    });
    return unsubscribe;
  }, [addListener, activeQueryClient]);

  return null;
}

/**
 * Mounts the preferences + lab store scoped to the current identity.
 * Guests use localStorage providers; signed-in users get server-backed
 * persistence. The `key` remounts the tree when identity changes, so guest
 * data is never mixed with (or overwritten by) account data.
 */
function IdentityProviders({ children }: { children: ReactNode }) {
  const { user, isLoaded } = useUser();
  const userId = isLoaded && user ? user.id : null;
  const identityKey = userId ? `user-${userId}` : 'guest';

  const labPersistence = useMemo(
    () => (userId ? createAuthenticatedPersistence() : undefined),
    [userId],
  );
  const preferencesPersistence = useMemo(
    () => (userId ? createAuthenticatedPreferencesPersistence() : undefined),
    [userId],
  );

  return (
    <PreferencesProvider
      key={identityKey}
      persistence={preferencesPersistence}
      hydrationFallback={<BootScreen />}
    >
      <LabProvider
        persistence={labPersistence}
        hydrationFallback={(props) => <WorkspaceGate {...props} />}
      >
        {children}
      </LabProvider>
    </PreferencesProvider>
  );
}

/**
 * Welcome routing for "/": first-time or signed-out visitors see the welcome
 * screen; returning users (signed in, or guests who already entered the
 * demo) land straight in the editor. Other routes always render the app —
 * using any shell route as a guest counts as entering the demo.
 */
function HomeGate({ children }: { children: ReactNode }) {
  const [location] = useLocation();
  const { isLoaded, isSignedIn } = useUser();
  const [guestEntered, setGuestEntered] = useState(() =>
    hasEnteredGuestSession(),
  );

  useEffect(() => {
    if (!guestEntered && location !== '/' && isLoaded && !isSignedIn) {
      markGuestSessionEntered();
      setGuestEntered(true);
    }
  }, [guestEntered, location, isLoaded, isSignedIn]);

  if (location === '/' && !isSignedIn && !guestEntered) {
    if (!isLoaded) return <BootScreen />;
    return (
      <WelcomePage
        onTryDemo={() => {
          markGuestSessionEntered();
          setGuestEntered(true);
        }}
      />
    );
  }

  return <>{children}</>;
}

function AppRoutes() {
  const [location] = useLocation();
  const isAuthRoute =
    location.startsWith('/sign-in') || location.startsWith('/sign-up');

  if (isAuthRoute) {
    return (
      <Switch>
        {/* REQUIRED — the /*? optional wildcard is the only wouter syntax that
            matches both the bare URL and Clerk's OAuth sub-paths. */}
        <Route path="/sign-in/*?" component={SignInPage} />
        <Route path="/sign-up/*?" component={SignUpPage} />
      </Switch>
    );
  }

  return (
    <HomeGate>
      <AppShell>
        <RoutedErrorBoundary>
          <Switch>
            <Route path="/" component={EditorPage} />
            <Route path="/editor/:documentId" component={EditorPage} />
            <Route path="/history" component={HistoryPage} />
            <Route
              path="/history/chats/:conversationId"
              component={ConversationPage}
            />
            <Route path="/compare" component={ComparePage} />
            <Route path="/benchmark" component={BenchmarkPage} />
            <Route path="/insights">{() => <InsightsPage tab="overview" />}</Route>
            <Route path="/insights/cost-context">
              {() => <InsightsPage tab="cost-context" />}
            </Route>
            <Route path="/insights/activity">
              {() => <InsightsPage tab="activity" />}
            </Route>
            <Route path="/settings" component={SettingsPage} />
            <Route path="/activity">
              {() => <Redirect to="/insights/activity" replace />}
            </Route>
            <Route path="/cost-context">
              {() => <Redirect to="/insights/cost-context" replace />}
            </Route>
            <Route component={NotFound} />
          </Switch>
        </RoutedErrorBoundary>
      </AppShell>
    </HomeGate>
  );
}

function RoutedErrorBoundary({ children }: { children: ReactNode }) {
  const [location] = useLocation();
  return <ErrorBoundary resetKey={location}>{children}</ErrorBoundary>;
}

function ClerkProviderWithApp() {
  const [, setLocation] = useLocation();

  return (
    <ClerkProvider
      publishableKey={clerkPubKey}
      proxyUrl={clerkProxyUrl}
      appearance={clerkAppearance}
      signInUrl={`${basePath}/sign-in`}
      signUpUrl={`${basePath}/sign-up`}
      signInFallbackRedirectUrl={basePath || '/'}
      signUpFallbackRedirectUrl={basePath || '/'}
      localization={{
        signIn: {
          start: {
            title: 'Welcome back',
            subtitle: 'Sign in to open your saved workspace',
          },
        },
        signUp: {
          start: {
            title: 'Create your account',
            subtitle: 'Keep documents, chats, and history across devices',
          },
        },
      }}
      routerPush={(to) => setLocation(stripBase(to))}
      routerReplace={(to) => setLocation(stripBase(to), { replace: true })}
    >
      <ClerkQueryClientCacheInvalidator />
      <IdentityProviders>
        <AppRoutes />
        <Toaster />
      </IdentityProviders>
    </ClerkProvider>
  );
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <WouterRouter base={basePath}>
          <ClerkProviderWithApp />
        </WouterRouter>
      </TooltipProvider>
    </QueryClientProvider>
  );
}

export default App;
