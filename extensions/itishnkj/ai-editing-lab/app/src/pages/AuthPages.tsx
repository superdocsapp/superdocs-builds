import type { ReactNode } from 'react';
import {
  ClerkFailed,
  ClerkLoaded,
  ClerkLoading,
  SignIn,
  SignUp,
} from '@clerk/react';
import { Loader2, PenLine } from 'lucide-react';
import { useLocation } from 'wouter';
import { Button } from '@/components/ui/button';
import { basePath } from '@/lib/clerk';
import { markGuestSessionEntered } from '@/lib/persistence';

/**
 * Sign-in / sign-up screens. Clerk renders the managed form; this frame adds
 * the app's loading state, a failure state with a guest escape hatch, and a
 * persistent "continue as guest" link so auth never blocks the demo path.
 */
function AuthPageFrame({
  children,
  testId,
}: {
  children: ReactNode;
  testId: string;
}) {
  const [, navigate] = useLocation();

  const continueAsGuest = () => {
    markGuestSessionEntered();
    navigate('/');
  };

  return (
    <div
      className="flex min-h-svh flex-col items-center justify-center gap-6 bg-background px-4 py-10"
      data-testid={testId}
    >
      <ClerkLoading>
        <div className="flex flex-col items-center gap-3" data-testid="auth-loading">
          <span className="flex h-10 w-10 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <PenLine className="h-5 w-5" />
          </span>
          <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
          <p className="text-sm text-muted-foreground">Loading sign-in…</p>
        </div>
      </ClerkLoading>

      <ClerkFailed>
        <div
          className="w-full max-w-sm rounded-xl border bg-card p-6 text-center"
          data-testid="auth-error"
        >
          <p className="text-sm font-medium">
            Couldn&apos;t sign you in. Try again or continue as guest.
          </p>
          <div className="mt-4 flex flex-col gap-2">
            <Button
              onClick={() => window.location.reload()}
              data-testid="button-auth-retry"
            >
              Try again
            </Button>
            <Button
              variant="outline"
              onClick={continueAsGuest}
              data-testid="button-auth-continue-guest"
            >
              Continue as guest
            </Button>
          </div>
        </div>
      </ClerkFailed>

      <ClerkLoaded>{children}</ClerkLoaded>

      <button
        type="button"
        onClick={continueAsGuest}
        className="text-xs text-muted-foreground underline-offset-4 hover:underline"
        data-testid="link-continue-as-guest"
      >
        Continue as guest instead
      </button>
    </div>
  );
}

export function SignInPage() {
  return (
    <AuthPageFrame testId="page-sign-in">
      {/* path must be the full browser path — Clerk reads window.location.pathname directly */}
      <SignIn
        routing="path"
        path={`${basePath}/sign-in`}
        signUpUrl={`${basePath}/sign-up`}
      />
    </AuthPageFrame>
  );
}

export function SignUpPage() {
  return (
    <AuthPageFrame testId="page-sign-up">
      <SignUp
        routing="path"
        path={`${basePath}/sign-up`}
        signInUrl={`${basePath}/sign-in`}
      />
    </AuthPageFrame>
  );
}
