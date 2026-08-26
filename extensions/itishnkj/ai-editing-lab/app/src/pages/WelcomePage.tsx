import { FileText, MessagesSquare, PenLine, Shapes } from 'lucide-react';
import { useLocation } from 'wouter';
import { Button } from '@/components/ui/button';

/**
 * First-run screen at "/" for signed-out visitors who haven't started the
 * demo yet. "Try the demo" enters the editor immediately as a guest —
 * signing in is never required.
 */
export default function WelcomePage({ onTryDemo }: { onTryDemo: () => void }) {
  const [, navigate] = useLocation();

  return (
    <div className="flex min-h-svh flex-col bg-background" data-testid="page-welcome">
      <main className="flex flex-1 flex-col items-center justify-center px-6 py-16">
        <div className="w-full max-w-md text-center">
          <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-primary text-primary-foreground">
            <PenLine className="h-6 w-6" />
          </span>
          <h1 className="mt-6 text-2xl font-semibold tracking-tight">
            AI Editing Lab
          </h1>
          <p className="mt-2 text-base text-muted-foreground">
            Edit documents with an AI assistant — and compare two editing
            engines side by side.
          </p>

          <div className="mt-8 flex flex-col gap-2">
            <Button size="lg" onClick={onTryDemo} data-testid="button-try-demo">
              Try the demo
            </Button>
            <Button
              size="lg"
              variant="outline"
              onClick={() => navigate('/sign-in')}
              data-testid="button-welcome-sign-in"
            >
              Sign in
            </Button>
          </div>

          <p className="mt-4 text-xs leading-relaxed text-muted-foreground">
            The demo starts instantly and keeps your work in this browser.
            Sign in to keep documents, chats, and history across devices.
          </p>

          <div className="mt-10 grid grid-cols-3 gap-3 text-left">
            <div className="rounded-lg border bg-card p-3">
              <FileText className="h-4 w-4 text-primary" />
              <p className="mt-2 text-xs font-medium">Your documents</p>
              <p className="mt-0.5 text-[11px] leading-snug text-muted-foreground">
                Use the sample or upload your own.
              </p>
            </div>
            <div className="rounded-lg border bg-card p-3">
              <MessagesSquare className="h-4 w-4 text-primary" />
              <p className="mt-2 text-xs font-medium">Chat to edit</p>
              <p className="mt-0.5 text-[11px] leading-snug text-muted-foreground">
                Review every change before it lands.
              </p>
            </div>
            <div className="rounded-lg border bg-card p-3">
              <Shapes className="h-4 w-4 text-primary" />
              <p className="mt-2 text-xs font-medium">Two engines</p>
              <p className="mt-0.5 text-[11px] leading-snug text-muted-foreground">
                Benchmark and compare results.
              </p>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
