import { useLocation } from 'wouter';
import { useClerk, useUser } from '@clerk/react';
import { Code2, LifeBuoy, LogOut, ShieldCheck, UserRound } from 'lucide-react';
import { toast } from 'sonner';
import {
  Avatar,
  AvatarFallback,
  AvatarImage,
} from '@/components/ui/avatar';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { EngineStatusList } from '@/components/layout/SystemStatusPopover';
import { basePath } from '@/lib/clerk';
import { usePreferences } from '@/lib/preferences';
import { useLabStore } from '@/lib/store';

function AccountCard() {
  const [, navigate] = useLocation();
  const { user } = useUser();
  const { signOut } = useClerk();
  const { flushPersistence } = useLabStore();

  const handleSignOut = async () => {
    try {
      await flushPersistence();
    } catch {
      // Sign-out proceeds even if the final save could not complete.
    }
    await signOut({ redirectUrl: basePath || '/' });
  };

  const displayName =
    user?.fullName?.trim() ||
    user?.username ||
    user?.primaryEmailAddress?.emailAddress ||
    'Your account';
  const email = user?.primaryEmailAddress?.emailAddress ?? '';
  const initials = user
    ? `${user.firstName?.[0] ?? ''}${user.lastName?.[0] ?? ''}`.toUpperCase() ||
      displayName.slice(0, 1).toUpperCase()
    : '';

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <UserRound className="h-4 w-4 text-primary" />
          Account
        </CardTitle>
        <CardDescription>
          {user
            ? 'Your documents, chats, and history are saved to your account.'
            : 'You’re working as a guest. Sign in to keep your work across devices.'}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {user ? (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border p-3">
            <div className="flex min-w-0 items-center gap-3">
              <Avatar className="h-9 w-9">
                <AvatarImage src={user.imageUrl} alt={displayName} />
                <AvatarFallback className="bg-primary/10 text-xs font-medium text-primary">
                  {initials}
                </AvatarFallback>
              </Avatar>
              <div className="min-w-0">
                <p
                  className="truncate text-sm font-medium"
                  data-testid="text-settings-account-name"
                >
                  {displayName}
                </p>
                {email ? (
                  <p className="truncate text-xs text-muted-foreground">
                    {email}
                  </p>
                ) : null}
              </div>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => void handleSignOut()}
              data-testid="button-settings-sign-out"
            >
              <LogOut className="mr-1.5 h-3.5 w-3.5" />
              Sign out
            </Button>
          </div>
        ) : (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border p-3">
            <div className="flex items-center gap-3">
              <span className="flex h-9 w-9 items-center justify-center rounded-full bg-muted text-muted-foreground">
                <UserRound className="h-4 w-4" />
              </span>
              <div>
                <p className="text-sm font-medium">Guest session</p>
                <p className="text-xs text-muted-foreground">
                  Work is saved in this browser only.
                </p>
              </div>
            </div>
            <Button
              size="sm"
              onClick={() => navigate('/sign-in')}
              data-testid="button-settings-sign-in"
            >
              Sign in to save your work
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default function SettingsPage() {
  const { preferences, setPreference } = usePreferences();
  const { persistenceMode } = useLabStore();
  const [, navigate] = useLocation();

  return (
    <div className="mx-auto max-w-2xl space-y-6 p-4 md:p-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Preferences for how the lab looks and how much technical detail it
          shows.
        </p>
      </header>

      <AccountCard />

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <Code2 className="h-4 w-4 text-primary" />
            Developer Mode
          </CardTitle>
          <CardDescription>
            Show request IDs, fingerprints, chunk metadata, and other technical
            diagnostics across the editor, review cards, and Insights.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between rounded-md border p-3">
            <Label htmlFor="developer-mode" className="cursor-pointer text-sm">
              {preferences.developerMode
                ? 'Technical details are visible'
                : 'Technical details are hidden'}
            </Label>
            <Switch
              id="developer-mode"
              checked={preferences.developerMode}
              onCheckedChange={(checked) => {
                setPreference('developerMode', checked);
                toast.success(
                  checked
                    ? 'Developer Mode on — technical details are now visible.'
                    : 'Developer Mode off — technical details are hidden.',
                );
              }}
              data-testid="switch-developer-mode"
            />
          </div>
          <p className="mt-3 flex items-start gap-1.5 text-xs text-muted-foreground">
            <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            This only changes what is displayed. Telemetry is always collected
            the same way, and every export includes the full data regardless of
            this setting.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">System status</CardTitle>
          <CardDescription>
            The editing engines available to this lab and whether they are
            ready to use.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <EngineStatusList showModels={preferences.developerMode} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <LifeBuoy className="h-4 w-4 text-primary" />
            Welcome tips
          </CardTitle>
          <CardDescription>
            Replay the short introduction that appears the first time you open
            the editor.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button
            variant="outline"
            onClick={() => {
              setPreference('onboardingDismissed', false);
              toast.success('Welcome tips will show on the editor.');
              navigate('/');
            }}
            data-testid="button-show-welcome-tips"
          >
            Show welcome tips again
          </Button>
        </CardContent>
      </Card>

      {persistenceMode === 'guest' ? (
        <p className="text-xs text-muted-foreground">
          You’re working in a guest session — documents, versions,
          conversations, and telemetry are stored only in this browser.
        </p>
      ) : (
        <p className="text-xs text-muted-foreground">
          Signed in — documents, versions, conversations, and preferences are
          saved to your account.
        </p>
      )}
    </div>
  );
}
