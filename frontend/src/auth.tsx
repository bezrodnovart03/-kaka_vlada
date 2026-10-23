import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

import * as client from './api/client';
import { api } from './api/endpoints';
import type { ISODate, MeOut } from './api/types';

interface AuthState {
  me: MeOut | null;
  isAdmin: boolean;
  /** «Сегодня» сервера (TIME_ZONE из .env) — фронт дату сам не считает. */
  today: ISODate;
  ready: boolean;
  signIn: (username: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

function browserToday(): ISODate {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<MeOut | null>(null);
  const [today, setToday] = useState<ISODate>(browserToday());
  const [ready, setReady] = useState(false);

  const loadProfile = useCallback(async () => {
    const [profile, summary] = await Promise.all([api.me(), api.summary()]);
    setMe(profile);
    setToday(summary.today);
  }, []);

  useEffect(() => {
    client.setUnauthorizedHandler(() => setMe(null));
    // При старте: если пользователь входил раньше, браузер сам приложит refresh-cookie.
    (async () => {
      try {
        if (await client.refreshAccess()) await loadProfile();
      } catch {
        client.setAccessToken(null);
      } finally {
        setReady(true);
      }
    })();
  }, [loadProfile]);

  const signIn = useCallback(
    async (username: string, password: string) => {
      await client.login(username, password);
      await loadProfile();
    },
    [loadProfile],
  );

  const signOut = useCallback(async () => {
    await client.logout().catch(() => undefined);
    setMe(null);
  }, []);

  const value = useMemo<AuthState>(
    () => ({ me, isAdmin: me?.role === 'admin', today, ready, signIn, signOut }),
    [me, today, ready, signIn, signOut],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth вне AuthProvider');
  return ctx;
}
