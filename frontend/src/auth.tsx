import { createContext, ReactNode, useContext, useEffect, useMemo, useState } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { getCurrentUser, login as loginApi, logout as logoutApi, registerUser, setAuthToken } from './api';

type User = {
  id: string;
  username: string;
  display_name?: string | null;
  role: 'admin' | 'operator' | 'viewer';
  status: string;
};

type AuthContextValue = {
  user: User | null;
  token: string | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  register: (username: string, password: string, invite_code: string) => Promise<void>;
  logout: () => Promise<void>;
  hasRole: (role: User['role']) => boolean;
};

const AuthContext = createContext<AuthContextValue | null>(null);
const TOKEN_KEY = 'ai-taobao-token';
const ROLE_RANK = { viewer: 1, operator: 2, admin: 3 };

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem(TOKEN_KEY));
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let ignore = false;
    setAuthToken(token);
    if (!token) {
      setUser(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    getCurrentUser()
      .then(({ data }) => {
        if (!ignore) setUser(data);
      })
      .catch(() => {
        if (!ignore) {
          localStorage.removeItem(TOKEN_KEY);
          setAuthToken(null);
          setToken(null);
          setUser(null);
        }
      })
      .finally(() => {
        if (!ignore) setLoading(false);
      });
    return () => {
      ignore = true;
    };
  }, [token]);

  const value = useMemo<AuthContextValue>(() => ({
    user,
    token,
    loading,
    async login(username: string, password: string) {
      const { data } = await loginApi({ username, password });
      localStorage.setItem(TOKEN_KEY, data.access_token);
      setAuthToken(data.access_token);
      setToken(data.access_token);
      setUser(data.user);
    },
    async register(username: string, password: string, invite_code: string) {
      const { data } = await registerUser({ username, password, invite_code });
      localStorage.setItem(TOKEN_KEY, data.access_token);
      setAuthToken(data.access_token);
      setToken(data.access_token);
      setUser(data.user);
    },
    async logout() {
      try {
        await logoutApi();
      } finally {
        localStorage.removeItem(TOKEN_KEY);
        setAuthToken(null);
        setToken(null);
        setUser(null);
      }
    },
    hasRole(role: User['role']) {
      if (!user) return false;
      return ROLE_RANK[user.role] >= ROLE_RANK[role];
    },
  }), [loading, token, user]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <div className="skeleton" style={{ height: 160, borderRadius: 'var(--radius-md)' }} />;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <>{children}</>;
}

export function RequireRole({ role, children }: { role: User['role']; children: ReactNode }) {
  const { hasRole } = useAuth();
  if (!hasRole(role)) {
    return <div className="empty-state">当前账号无权访问该功能</div>;
  }
  return <>{children}</>;
}
