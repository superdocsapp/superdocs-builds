import { publishableKeyFromHost } from '@clerk/react/internal';

/**
 * Clerk configuration shared by App.tsx and the auth pages.
 *
 * The key/proxy wiring below is required verbatim: the same build runs in
 * development and production — env vars that are empty in dev are
 * auto-populated in prod, so none of this may be gated on NODE_ENV/PROD.
 */

// REQUIRED — resolves the key from window.location.hostname so the same
// build serves multiple Clerk custom domains. Do not inline the env var.
export const clerkPubKey = publishableKeyFromHost(
  window.location.hostname,
  import.meta.env.VITE_CLERK_PUBLISHABLE_KEY,
);

// REQUIRED — empty in dev (Clerk hits the dev Frontend API directly),
// auto-set in prod. Must be passed to <ClerkProvider> unconditionally.
export const clerkProxyUrl = import.meta.env.VITE_CLERK_PROXY_URL;

export const basePath = import.meta.env.BASE_URL.replace(/\/$/, '');

// Clerk passes full paths to routerPush/routerReplace, but wouter's
// setLocation prepends the base — strip it to avoid doubling.
export function stripBase(path: string): string {
  return basePath && path.startsWith(basePath)
    ? path.slice(basePath.length) || '/'
    : path;
}

if (!clerkPubKey) {
  throw new Error('Missing VITE_CLERK_PUBLISHABLE_KEY environment variable');
}

/** Matches the app's warm document theme (see index.css). */
export const clerkAppearance = {
  theme: 'simple' as const,
  cssLayerName: 'clerk',
  options: {
    logoPlacement: 'inside' as const,
    logoLinkUrl: basePath || '/',
    logoImageUrl: `${window.location.origin}${basePath}/logo.svg`,
  },
  variables: {
    colorPrimary: 'hsl(178, 84%, 24%)',
    colorForeground: 'hsl(30, 12%, 16%)',
    colorMutedForeground: 'hsl(30, 8%, 42%)',
    colorDanger: 'hsl(0, 72%, 45%)',
    colorBackground: 'hsl(0, 0%, 100%)',
    colorInput: 'hsl(0, 0%, 100%)',
    colorInputForeground: 'hsl(30, 12%, 16%)',
    colorNeutral: 'hsl(30, 12%, 16%)',
    fontFamily: "'Inter', sans-serif",
    borderRadius: '0.5rem',
  },
  elements: {
    rootBox: 'w-full flex justify-center',
    // cardBox must own the single card surface (card/footer are transparent).
    cardBox:
      'bg-white border border-[hsl(38,18%,89%)] rounded-2xl w-[420px] max-w-full overflow-hidden shadow-lg',
    card: '!shadow-none !border-0 !bg-transparent !rounded-none',
    footer: '!shadow-none !border-0 !bg-transparent !rounded-none',
    headerTitle: 'text-[hsl(30,12%,16%)] font-semibold',
    headerSubtitle: 'text-[hsl(30,8%,42%)]',
    formButtonPrimary: '!shadow-none',
    logoBox: 'justify-center',
  },
};
