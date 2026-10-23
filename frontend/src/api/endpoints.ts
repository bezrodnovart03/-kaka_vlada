import { request } from './client';
import type {
  MeOut,
  OccurrenceFilter,
  Paginated,
  PageQuery,
  PaymentOccurrenceOut,
  PaymentOccurrencePatchIn,
  RecurringPaymentFilter,
  RecurringPaymentIn,
  RecurringPaymentOut,
  SummaryOut,
  SummaryQuery,
  UserCreateIn,
  UserOut,
  UserPatchIn,
} from './types';

type Q = Record<string, string | number | boolean | undefined>;

export const api = {
  me: () => request<MeOut>('/auth/me'),

  recurring: {
    list: (query: RecurringPaymentFilter = {}) =>
      request<Paginated<RecurringPaymentOut>>('/recurring-payments', { query: query as Q }),
    create: (body: RecurringPaymentIn) =>
      request<RecurringPaymentOut>('/recurring-payments', { method: 'POST', body }),
    remove: (id: number) => request<null>(`/recurring-payments/${id}`, { method: 'DELETE' }),
  },

  occurrences: {
    list: (query: OccurrenceFilter = {}) =>
      request<Paginated<PaymentOccurrenceOut>>('/payment-occurrences', { query: query as Q }),
    get: (id: number) => request<PaymentOccurrenceOut>(`/payment-occurrences/${id}`),
    patch: (id: number, body: PaymentOccurrencePatchIn) =>
      request<PaymentOccurrenceOut>(`/payment-occurrences/${id}`, { method: 'PATCH', body }),
  },

  summary: (query: SummaryQuery = {}) =>
    request<SummaryOut>('/payments/summary', { query: query as Q }),

  users: {
    list: (query: PageQuery = {}) => request<Paginated<UserOut>>('/users', { query: query as Q }),
    create: (body: UserCreateIn) => request<UserOut>('/users', { method: 'POST', body }),
    patch: (id: number, body: UserPatchIn) =>
      request<UserOut>(`/users/${id}`, { method: 'PATCH', body }),
    remove: (id: number) => request<null>(`/users/${id}`, { method: 'DELETE' }),
  },
};
