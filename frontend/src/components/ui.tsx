import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react';

import { ApiError } from '../api/client';
import type { Currency, PaymentOccurrenceOut } from '../api/types';
import { days, formatDate } from '../format';

// ── тосты ────────────────────────────────────────────────

type ToastKind = 'ok' | 'error';
interface Toast {
  id: number;
  kind: ToastKind;
  text: string;
}

const ToastContext = createContext<(text: string, kind?: ToastKind) => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);
  const push = useCallback((text: string, kind: ToastKind = 'ok') => {
    const id = nextId.current++;
    setToasts((list) => [...list, { id, kind, text }]);
    setTimeout(() => setToasts((list) => list.filter((t) => t.id !== id)), 4000);
  }, []);
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast toast-${t.kind}`}>
            {t.text}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const push = useContext(ToastContext);
  return {
    ok: (text: string) => push(text, 'ok'),
    /** 403 → «Недостаточно прав», остальное — текст из ErrorOut.detail. */
    error: (error: unknown) => {
      if (error instanceof ApiError) {
        push(error.status === 403 && error.code === 'forbidden' ? 'Недостаточно прав' : error.message, 'error');
      } else {
        push('Что-то пошло не так', 'error');
      }
    },
  };
}

// ── загрузка данных ──────────────────────────────────────

export function useLoader<T>(load: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    load()
      .then((result) => {
        if (!cancelled) {
          setData(result);
          setError(null);
        }
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof ApiError ? e : new ApiError(0, null));
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [...deps, version]);

  const reload = useCallback(() => setVersion((v) => v + 1), []);
  return { data, error, loading, reload };
}

// ── мелкие компоненты ────────────────────────────────────

export function StatusBadge({ occurrence }: { occurrence: PaymentOccurrenceOut }) {
  if (occurrence.status === 'paid') {
    return occurrence.is_overdue ? (
      <span className="badge badge-warn" title="Оплачено позже срока">
        Оплачено с опозданием
      </span>
    ) : (
      <span className="badge badge-ok">Оплачено</span>
    );
  }
  return occurrence.is_overdue ? (
    <span className="badge badge-danger">Просрочено</span>
  ) : (
    <span className="badge badge-muted">Не оплачено</span>
  );
}

export function OverdueCell({ occurrence }: { occurrence: PaymentOccurrenceOut }) {
  if (occurrence.overdue_days <= 0) return <span className="muted">—</span>;
  return <span className="text-danger">{days(occurrence.overdue_days)}</span>;
}

export function DueCell({ occurrence, today }: { occurrence: PaymentOccurrenceOut; today: string }) {
  const diff = Math.round((Date.parse(occurrence.due_date) - Date.parse(today)) / 86400000);
  let hint = '';
  if (occurrence.status === 'unpaid') {
    if (diff === 0) hint = 'сегодня';
    else if (diff === 1) hint = 'завтра';
    else if (diff > 1 && diff <= 7) hint = `через ${days(diff)}`;
  }
  return (
    <>
      {formatDate(occurrence.due_date)}
      {hint && <div className="hint">{hint}</div>}
    </>
  );
}

export function CurrencyTag({ currency }: { currency: Currency }) {
  return <span className={`cur cur-${currency}`}>{currency}</span>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function ErrorBox({ error }: { error: ApiError | null }) {
  if (!error) return null;
  return <div className="alert">{error.message}</div>;
}

export function Pager({
  page,
  pageSize,
  count,
  onPage,
}: {
  page: number;
  pageSize: number;
  count: number;
  onPage: (page: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(count / pageSize));
  if (pages <= 1) return null;
  return (
    <div className="pager">
      <button className="btn btn-ghost" disabled={page <= 1} onClick={() => onPage(page - 1)}>
        ←
      </button>
      <span>
        {page} / {pages}
      </span>
      <button className="btn btn-ghost" disabled={page >= pages} onClick={() => onPage(page + 1)}>
        →
      </button>
    </div>
  );
}

export function Modal({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal-head">
          <h2>{title}</h2>
          <button className="btn btn-ghost" onClick={onClose} aria-label="Закрыть">
            ✕
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function FieldError({ error, name }: { error: ApiError | null; name: string }) {
  const messages = error?.fields[name];
  if (!messages?.length) return null;
  return <div className="field-error">{messages.join(', ')}</div>;
}
