import type { Currency, ISODate, Money, Period, ReminderChannel } from './api/types';

// Арифметику с деньгами фронт не делает — только форматирование (docs/API.md §1).
const money = new Map<string, Intl.NumberFormat>();

export function formatMoney(amount: Money, currency: Currency): string {
  let fmt = money.get(currency);
  if (!fmt) {
    fmt = new Intl.NumberFormat('ru-RU', { style: 'currency', currency });
    money.set(currency, fmt);
  }
  return fmt.format(Number(amount));
}

export function formatDate(value: ISODate | null | undefined): string {
  if (!value) return '—';
  const [y, m, d] = value.slice(0, 10).split('-');
  return `${d}.${m}.${y}`;
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—';
  return new Date(value).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export const PERIOD_LABEL: Record<Period, string> = {
  monthly: 'Ежемесячно',
  quarterly: 'Ежеквартально',
  yearly: 'Ежегодно',
};

export const CURRENCIES: Currency[] = ['RUB', 'USD', 'EUR'];

export const CHANNEL_LABEL: Record<ReminderChannel, string> = {
  telegram: 'Telegram',
  email: 'Email',
  webhook: 'Webhook',
  apprise: 'другие каналы',
};

export function plural(n: number, one: string, few: string, many: string): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
}

export function days(n: number): string {
  return `${n} ${plural(n, 'день', 'дня', 'дней')}`;
}

// Даты как строки YYYY-MM-DD без часовых поясов браузера.
export function isoDate(year: number, month: number, day: number): ISODate {
  return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
}

/** Сдвиг на n месяцев; нет такого числа в месяце — последний день (как на бэкенде). */
export function addMonths(iso: ISODate, n: number): ISODate {
  const [y, m, d] = iso.split('-').map(Number);
  const target = new Date(Date.UTC(y, m - 1 + n, 1));
  const lastDay = new Date(Date.UTC(target.getUTCFullYear(), target.getUTCMonth() + 1, 0)).getUTCDate();
  return isoDate(target.getUTCFullYear(), target.getUTCMonth() + 1, Math.min(d, lastDay));
}

export function monthBounds(iso: ISODate, offsetMonths = 0): [ISODate, ISODate] {
  const [y, m] = iso.split('-').map(Number);
  const first = new Date(Date.UTC(y, m - 1 + offsetMonths, 1));
  const last = new Date(Date.UTC(first.getUTCFullYear(), first.getUTCMonth() + 1, 0));
  return [first.toISOString().slice(0, 10), last.toISOString().slice(0, 10)];
}

export const MONTHS = [
  'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
  'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь',
];
