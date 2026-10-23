
// ── общие ──────────────────────────────────────────────
export type ISODate = string;      // '2026-10-23'
export type ISODateTime = string;  // '2026-10-23T20:18:00+03:00'
export type Money = string;        // '85000.00'

export type Role = 'admin' | 'user';
export type Currency = 'RUB' | 'USD' | 'EUR';
export type Period = 'monthly' | 'quarterly' | 'yearly';
export type OccurrenceStatus = 'unpaid' | 'paid';
export type OccurrenceState = 'unpaid' | 'paid' | 'overdue' | 'upcoming';

export interface UserBrief { id: number; username: string; }

export type ErrorCode =
  | 'unauthorized' | 'invalid_credentials' | 'token_invalid' | 'forbidden' | 'csrf_failed'
  | 'not_found' | 'validation_error' | 'conflict'
  | 'env_admin_immutable' | 'cannot_delete_self'
  | 'username_taken' | 'already_deleted' | 'occurrence_not_paid';

export interface ErrorOut {
  code: ErrorCode;
  detail: string;
  fields?: Record<string, string[]> | null;
}

export interface Paginated<T> { items: T[]; count: number; }
export interface PageQuery { page?: number; page_size?: number; }

// ── авторизация ────────────────────────────────────────
export interface LoginIn { username: string; password: string; }
// refresh-токен живёт только в HttpOnly-cookie и в TS не фигурирует
export interface AccessOut { access: string; }

export interface MeOut {
  id: number;
  username: string;
  first_name: string;   // '' если не задано
  last_name: string;
  email: string;
  role: Role;
  is_env_admin: boolean;
}

// ── регулярные платежи ─────────────────────────────────
export interface RecurringPaymentIn {
  title: string;
  amount: Money;
  currency: Currency;
  first_due_date: ISODate;
  period?: Period;          // по умолчанию 'monthly'
  comment?: string | null;
}

export interface OccurrenceBrief {
  id: number;
  due_date: ISODate;
  status: OccurrenceStatus;
  paid_at: ISODate | null;
  is_overdue: boolean;
}

export interface RecurringPaymentOut {
  id: number;
  title: string;
  amount: Money;
  currency: Currency;
  period: Period;
  anchor_day: number;
  first_due_date: ISODate;
  comment: string | null;
  is_active: boolean;
  deleted_at: ISODateTime | null;
  created_by: UserBrief;
  created_at: ISODateTime;
  next_occurrence: OccurrenceBrief | null;
  overdue_count: number;
}

export interface RecurringPaymentFilter extends PageQuery {
  currency?: Currency;
  search?: string;
  include_inactive?: boolean;
}

// ── периоды оплаты ─────────────────────────────────────
export interface RecurringPaymentBrief { id: number; title: string; is_active: boolean; }

export interface PaymentOccurrenceOut {
  id: number;
  recurring_payment: RecurringPaymentBrief;
  amount: Money;
  currency: Currency;
  due_date: ISODate;
  status: OccurrenceStatus;
  paid_at: ISODate | null;
  is_overdue: boolean;
  overdue_days: number;
  marked_by: UserBrief | null;
  marked_at: ISODateTime | null;
  reminder_sent_at: ISODateTime | null;
}

export type PaymentOccurrencePatchIn =
  | { status: 'paid'; paid_at?: ISODate }   // отметить; без paid_at = сегодня
  | { status: 'unpaid' }                     // отменить; paid_at очищается
  | { paid_at: ISODate };                    // исправить дату уже оплаченного

export interface OccurrenceFilter extends PageQuery {
  recurring_payment_id?: number;
  currency?: Currency;
  state?: OccurrenceState;
  due_from?: ISODate;
  due_to?: ISODate;
  ordering?: 'due_date' | '-due_date';
}

// ── итоги ──────────────────────────────────────────────
export interface SummaryQuery { date_from?: ISODate; date_to?: ISODate; }

export interface CurrencyTotals {
  currency: Currency;
  planned: Money;
  paid: Money;
  unpaid: Money;
  overdue: Money;
  count_planned: number;
  count_paid: number;
  count_overdue: number;
}

export interface SummaryOut {
  date_from: ISODate;
  date_to: ISODate;
  today: ISODate;
  totals: CurrencyTotals[];  // всегда RUB, USD, EUR
}

// ── пользователи ───────────────────────────────────────
export interface UserOut {
  id: number;
  username: string;
  first_name: string;
  last_name: string;
  email: string;
  role: Role;
  is_env_admin: boolean;
  is_active: boolean;
  last_login: ISODateTime | null;
  date_joined: ISODateTime;
}

export interface UserCreateIn {
  username: string;
  password: string;
  email?: string;
  first_name?: string;
  last_name?: string;
}

export interface UserPatchIn {
  username?: string;
  password?: string;    // отзывает refresh-токены пользователя
  email?: string;
  first_name?: string;
  last_name?: string;
  is_active?: boolean;  // false — блокировка без удаления
}
