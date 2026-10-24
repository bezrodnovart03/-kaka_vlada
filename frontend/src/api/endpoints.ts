import { download, request } from './client';
import type {
  AttachmentLinkIn,
  AttachmentOut,
  CalendarQuery,
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
    exportCalendar: (query: CalendarQuery = {}) =>
      download('/payment-occurrences/calendar.ics', query as Q, 'invoice-keeper.ics'),
  },

  attachments: {
    list: (occurrenceId: number) =>
      request<AttachmentOut[]>(`/payment-occurrences/${occurrenceId}/attachments`),
    uploadFile: (occurrenceId: number, file: File) => {
      const body = new FormData();
      body.append('file', file);
      return request<AttachmentOut>(`/payment-occurrences/${occurrenceId}/attachments/file`, {
        method: 'POST',
        body,
      });
    },
    addLink: (occurrenceId: number, body: AttachmentLinkIn) =>
      request<AttachmentOut>(`/payment-occurrences/${occurrenceId}/attachments/link`, {
        method: 'POST',
        body,
      }),
    download: (occurrenceId: number, attachment: AttachmentOut) =>
      download(
        `/payment-occurrences/${occurrenceId}/attachments/${attachment.id}/download`,
        undefined,
        attachment.name,
      ),
    remove: (occurrenceId: number, attachmentId: number) =>
      request<null>(`/payment-occurrences/${occurrenceId}/attachments/${attachmentId}`, {
        method: 'DELETE',
      }),
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
