import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from 'react';
import type { AuthenticatedPreferencesPersistence } from './persistence';

/**
 * Presentation preferences. Deliberately stored under their own key so that
 * "Reset demo" (which rebuilds lab state) never re-triggers onboarding or
 * flips Developer Mode. These flags only change what is DISPLAYED — telemetry
 * collection is identical whether Developer Mode is on or off.
 *
 * Guests keep the original localStorage behavior. Signed-in users get the
 * same preferences loaded from and saved to their account (pass a
 * `persistence` provider and remount with a user-scoped `key`).
 */
export type LabPreferences = {
  developerMode: boolean;
  onboardingDismissed: boolean;
  sidebarCollapsed: boolean;
};

const PREFERENCES_STORAGE_KEY = 'ai-editing-lab-preferences-v1';

const DEFAULT_PREFERENCES: LabPreferences = {
  developerMode: false,
  onboardingDismissed: false,
  sidebarCollapsed: false,
};

type PreferencesContextValue = {
  preferences: LabPreferences;
  setPreference: <K extends keyof LabPreferences>(
    key: K,
    value: LabPreferences[K],
  ) => void;
};

const PreferencesContext = createContext<PreferencesContextValue | undefined>(
  undefined,
);

function loadGuestPreferences(): LabPreferences {
  try {
    const stored = localStorage.getItem(PREFERENCES_STORAGE_KEY);
    if (stored) {
      return { ...DEFAULT_PREFERENCES, ...(JSON.parse(stored) as object) };
    }
  } catch {
    // Corrupt preferences fall back to defaults; nothing else is affected.
  }
  return DEFAULT_PREFERENCES;
}

export function PreferencesProvider({
  children,
  persistence,
  hydrationFallback = null,
}: {
  children: React.ReactNode;
  /** Server-backed storage for signed-in users; omit for guest localStorage. */
  persistence?: AuthenticatedPreferencesPersistence;
  /** Rendered while account preferences load (authenticated mode only). */
  hydrationFallback?: React.ReactNode;
}) {
  // The provider is fixed for the lifetime of this mount; identity changes
  // remount the provider tree with a new `key` in App.tsx.
  const [provider] = useState(() => persistence ?? null);
  const [preferences, setPreferences] = useState<LabPreferences>(() =>
    provider ? DEFAULT_PREFERENCES : loadGuestPreferences(),
  );
  const [hydrated, setHydrated] = useState(provider == null);
  const skipNextPersistRef = useRef(true);

  useEffect(() => {
    if (!provider || hydrated) return;
    let cancelled = false;
    provider
      .load()
      .then((stored) => {
        if (cancelled || !stored) return;
        setPreferences({
          ...DEFAULT_PREFERENCES,
          ...(stored as Partial<LabPreferences>),
        });
      })
      .catch(() => {
        // Defaults are fine; preferences are not worth blocking the app for.
      })
      .finally(() => {
        if (!cancelled) {
          skipNextPersistRef.current = true;
          setHydrated(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [provider, hydrated]);

  useEffect(() => {
    if (!hydrated) return;
    if (skipNextPersistRef.current) {
      skipNextPersistRef.current = false;
      return;
    }
    if (provider) {
      provider.persist(preferences);
      return;
    }
    try {
      localStorage.setItem(PREFERENCES_STORAGE_KEY, JSON.stringify(preferences));
    } catch {
      // Storage may be unavailable (private browsing); preferences stay in memory.
    }
  }, [preferences, hydrated, provider]);

  const setPreference = useCallback(
    <K extends keyof LabPreferences>(key: K, value: LabPreferences[K]) => {
      setPreferences((current) => ({ ...current, [key]: value }));
    },
    [],
  );

  const value = React.useMemo(
    () => ({ preferences, setPreference }),
    [preferences, setPreference],
  );

  if (provider && !hydrated) {
    return <>{hydrationFallback}</>;
  }

  return (
    <PreferencesContext.Provider value={value}>
      {children}
    </PreferencesContext.Provider>
  );
}

export function usePreferences() {
  const context = useContext(PreferencesContext);
  if (!context) {
    throw new Error('usePreferences must be used within PreferencesProvider');
  }
  return context;
}
