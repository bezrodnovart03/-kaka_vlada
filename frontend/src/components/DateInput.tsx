import { useCallback, useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent } from 'react';
import { createPortal } from 'react-dom';

import type { ISODate } from '../api/types';
import { addMonths, formatDate, MONTHS } from '../format';

const WEEKDAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
const DAY_MS = 86400000;

// Даты — строки YYYY-MM-DD; считаем в UTC, чтобы часовой пояс браузера не сдвигал день.
function toUtc(iso: ISODate): number {
  const [y, m, d] = iso.split('-').map(Number);
  return Date.UTC(y, m - 1, d);
}

function fromUtc(ms: number): ISODate {
  return new Date(ms).toISOString().slice(0, 10);
}

function addDays(iso: ISODate, n: number): ISODate {
  return fromUtc(toUtc(iso) + n * DAY_MS);
}

/** 6 недель с понедельника, включая хвосты соседних месяцев — сетка не прыгает по высоте. */
function monthGrid(monthIso: ISODate): ISODate[] {
  const first = `${monthIso.slice(0, 8)}01`;
  const weekday = (new Date(toUtc(first)).getUTCDay() + 6) % 7;
  const start = addDays(first, -weekday);
  return Array.from({ length: 42 }, (_, i) => addDays(start, i));
}

function clamp(iso: ISODate, min?: ISODate, max?: ISODate): ISODate {
  if (min && iso < min) return min;
  if (max && iso > max) return max;
  return iso;
}

const POPOVER_WIDTH = 288;

/**
 * Поле даты в стиле панели вместо системного `<input type="date">`:
 * одинаково во всех браузерах, сетка месяца как на странице «Календарь оплат».
 * Попап рисуется в портале — `.modal` с overflow: auto иначе обрезает его.
 */
export function DateInput({
  value,
  onChange,
  min,
  max,
  today,
  'aria-label': ariaLabel,
}: {
  value: ISODate;
  onChange: (value: ISODate) => void;
  min?: ISODate;
  max?: ISODate;
  /** «Сегодня» сервера (MeOut/SummaryOut.today) — фронт дату сам не считает. */
  today: ISODate;
  'aria-label'?: string;
}) {
  const [open, setOpen] = useState(false);
  const [focused, setFocused] = useState<ISODate>(value || today);
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const gridRef = useRef<HTMLDivElement>(null);

  const close = useCallback((returnFocus: boolean) => {
    setOpen(false);
    setPosition(null);
    if (returnFocus) triggerRef.current?.focus();
  }, []);

  function toggle() {
    if (open) return close(false);
    setFocused(clamp(value || today, min, max));
    setOpen(true);
  }

  function select(iso: ISODate) {
    onChange(iso);
    close(true);
  }

  // Позиция под полем; если снизу не помещается — над ним. Высоту берём у уже отрисованного
  // (пока невидимого) попапа. Пересчёт при скролле модалки и ресайзе.
  useLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      const rect = triggerRef.current?.getBoundingClientRect();
      const height = popoverRef.current?.offsetHeight ?? 0;
      if (!rect) return;
      const below = rect.bottom + 6;
      const above = rect.top - height - 6;
      const viewport = window.innerHeight;
      let top: number;
      if (below + height <= viewport - 8) top = below;
      else if (above >= 8) top = above;
      // Низкое окно: ни сверху, ни снизу не помещается — держим попап целиком в окне.
      else top = Math.max(8, Math.min(below, viewport - height - 8));
      const left = Math.min(rect.left, window.innerWidth - POPOVER_WIDTH - 8);
      setPosition({ top, left: Math.max(8, left) });
    };
    place();
    window.addEventListener('resize', place);
    window.addEventListener('scroll', place, true);
    return () => {
      window.removeEventListener('resize', place);
      window.removeEventListener('scroll', place, true);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      const target = e.target as Node;
      if (!popoverRef.current?.contains(target) && !triggerRef.current?.contains(target)) close(false);
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [open, close]);

  // Клавиатура: фокус всегда на выбранной в сетке дате.
  useEffect(() => {
    if (open) gridRef.current?.querySelector<HTMLButtonElement>(`[data-date="${focused}"]`)?.focus();
  }, [open, focused, position]);

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    const moves: Record<string, () => ISODate> = {
      ArrowLeft: () => addDays(focused, -1),
      ArrowRight: () => addDays(focused, 1),
      ArrowUp: () => addDays(focused, -7),
      ArrowDown: () => addDays(focused, 7),
      PageUp: () => addMonths(focused, -1),
      PageDown: () => addMonths(focused, 1),
    };
    if (e.key === 'Escape') {
      // Не даём Escape дойти до Modal: закрываем только календарь.
      e.stopPropagation();
      close(true);
    } else if (moves[e.key]) {
      e.preventDefault();
      setFocused(clamp(moves[e.key](), min, max));
    }
  }

  const disabled = (iso: ISODate) => Boolean((min && iso < min) || (max && iso > max));
  const [year, month] = focused.split('-').map(Number);
  const monthPrefix = focused.slice(0, 7);
  const prevMonth = addMonths(focused, -1);
  const nextMonth = addMonths(focused, 1);

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className={`date-input ${open ? 'date-input-open' : ''}`}
        onClick={toggle}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={ariaLabel ? `${ariaLabel}: ${formatDate(value)}` : undefined}
      >
        <span className={value ? '' : 'muted'}>{value ? formatDate(value) : 'дд.мм.гггг'}</span>
        <svg className="date-input-icon" viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
          <rect x="2" y="3" width="12" height="11" rx="2" fill="none" stroke="currentColor" strokeWidth="1.4" />
          <path d="M2 6.5h12M5.5 1.5v3M10.5 1.5v3" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
        </svg>
      </button>
      {open &&
        createPortal(
          <div
            ref={popoverRef}
            className="datepicker"
            role="dialog"
            aria-label="Выбор даты"
            style={
              position
                ? { top: position.top, left: position.left, width: POPOVER_WIDTH }
                : { top: 0, left: 0, width: POPOVER_WIDTH, visibility: 'hidden' }
            }
            onKeyDown={onKeyDown}
          >
            <div className="datepicker-head">
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setFocused(clamp(prevMonth, min, max))}
                disabled={Boolean(min && prevMonth.slice(0, 7) < min.slice(0, 7))}
                aria-label="Предыдущий месяц"
              >
                ←
              </button>
              <strong>
                {MONTHS[month - 1]} {year}
              </strong>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setFocused(clamp(nextMonth, min, max))}
                disabled={Boolean(max && nextMonth.slice(0, 7) > max.slice(0, 7))}
                aria-label="Следующий месяц"
              >
                →
              </button>
            </div>
            <div className="datepicker-grid" ref={gridRef} role="grid">
              {WEEKDAYS.map((d) => (
                <div key={d} className="datepicker-weekday">
                  {d}
                </div>
              ))}
              {monthGrid(focused).map((iso) => {
                const classes = [
                  'datepicker-day',
                  iso.slice(0, 7) !== monthPrefix && 'datepicker-outside',
                  iso === today && 'datepicker-today',
                  iso === value && 'datepicker-selected',
                ]
                  .filter(Boolean)
                  .join(' ');
                return (
                  <button
                    key={iso}
                    type="button"
                    data-date={iso}
                    className={classes}
                    disabled={disabled(iso)}
                    tabIndex={iso === focused ? 0 : -1}
                    aria-selected={iso === value}
                    aria-label={formatDate(iso)}
                    onClick={() => select(iso)}
                  >
                    {Number(iso.slice(8, 10))}
                  </button>
                );
              })}
            </div>
            <div className="datepicker-foot">
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                disabled={disabled(today)}
                onClick={() => select(today)}
              >
                Сегодня
              </button>
            </div>
          </div>,
          document.body,
        )}
    </>
  );
}
