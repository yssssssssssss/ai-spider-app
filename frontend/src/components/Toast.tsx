import { createContext, useContext, useState, useCallback, useEffect, ReactNode } from 'react';
import { registerToast } from '../api';

interface Toast {
  id: string;
  message: string;
  type: 'success' | 'error' | 'warning' | 'info';
}

interface ToastContextType {
  toasts: Toast[];
  showToast: (message: string, type?: Toast['type']) => void;
  removeToast: (id: string) => void;
}

const ToastContext = createContext<ToastContextType | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const showToast = useCallback((message: string, type: Toast['type'] = 'info') => {
    const id = Math.random().toString(36).slice(2, 9);
    setToasts(prev => [...prev, { id, message, type }]);
    setTimeout(() => {
      setToasts(prev => prev.filter(t => t.id !== id));
    }, 4000);
  }, []);

  const removeToast = useCallback((id: string) => {
    setToasts(prev => prev.filter(t => t.id !== id));
  }, []);

  // 注册到 API 模块，让拦截器也能弹出 Toast
  useEffect(() => {
    registerToast(showToast);
  }, [showToast]);

  return (
    <ToastContext.Provider value={{ toasts, showToast, removeToast }}>
      {children}
      <div
        role="status"
        aria-live="polite"
        aria-atomic="true"
        style={{
          position: 'fixed',
          top: 20,
          right: 20,
          zIndex: 9999,
          display: 'flex',
          flexDirection: 'column',
          gap: 8,
        }}
      >
        {toasts.map(t => (
          <div
            key={t.id}
            className="animate-fade-in"
            style={{
              padding: '12px 20px',
              borderRadius: 'var(--radius-md)',
              background: t.type === 'error' ? '#ef4444' : t.type === 'success' ? '#22c55e' : 'var(--bg-card)',
              color: t.type === 'error' || t.type === 'success' ? '#fff' : 'var(--text-primary)',
              border: t.type === 'error' || t.type === 'success' ? 'none' : '1px solid var(--border)',
              boxShadow: 'var(--shadow-lg)',
              fontSize: '0.875rem',
              fontWeight: 500,
              minWidth: 200,
              display: 'flex',
              alignItems: 'center',
              gap: 8,
            }}
          >
            {t.type === 'error' && '⚠️ '}
            {t.type === 'success' && '✅ '}
            {t.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used within ToastProvider');
  return ctx;
}
