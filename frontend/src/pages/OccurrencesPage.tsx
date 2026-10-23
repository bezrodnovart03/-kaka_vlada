import { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

import { api } from '../api/endpoints';
import type { Currency, OccurrenceState, PaymentOccurrenceOut } from '../api/types';
import { useAuth } from '../auth';
import { OccurrenceActions } from '../components/OccurrenceActions';
import { SummaryCards } from '../components/SummaryCards';
import {
  CurrencyTag,
  DueCell,
  Empty,
  ErrorBox,
  OverdueCell,
  Pager,
  StatusBadge,
  useLoader,
} from '../components/ui';
import { CURRENCIES, formatDate, formatDateTime, formatMoney, monthBounds, MONTHS } from '../format';

const TABS: { state: OccurrenceState | ''; label: string }[] = [
  { state: '', label: 'Все' },
  { state: 'overdue', label: 'Просроченные' },
  { state: 'upcoming', label: 'Предстоящие' },
  { state: 'paid', label: 'Оплаченные' },
];

const PAGE_SIZE = 25;

/** Главная: что и когда оплатить, что оплачено, что просрочено. */
export function OccurrencesPage() {
  const { today } = useAuth();
  const [params, setParams] = useSearchParams();
  const state = (params.get('state') ?? '') as OccurrenceState | '';
  const currency = (params.get('currency') ?? '') as Currency | '';
  const paymentId = params.get('payment');
  const page = Number(params.get('page') ?? 1);

  function update(next: Record<string, string | null>) {
    const merged = new URLSearchParams(params);
    for (const [k, v] of Object.entries(next)) {
      if (v) merged.set(k, v);
      else merged.delete(k);
    }
    if (!('page' in next)) merged.delete('page');
    setParams(merged, { replace: true });
  }

  const [monthFrom, monthTo] = monthBounds(today);
  const summary = useLoader(() => api.summary({ date_from: monthFrom, date_to: monthTo }), [monthFrom]);
  const list = useLoader(
    () =>
      api.occurrences.list({
        state: state || undefined,
        currency: currency || undefined,
        recurring_payment_id: paymentId ? Number(paymentId) : undefined,
        // Просрочки — самые старые первыми, оплаченные — свежие первыми.
        ordering: state === 'paid' ? '-due_date' : 'due_date',
        page,
        page_size: PAGE_SIZE,
      }),
    [state, currency, paymentId, page],
  );
  const [overrides, setOverrides] = useState<Record<number, PaymentOccurrenceOut>>({});

  function changed(updated: PaymentOccurrenceOut) {
    setOverrides((o) => ({ ...o, [updated.id]: updated }));
    summary.reload();
  }

  const items = (list.data?.items ?? []).map((item) => overrides[item.id] ?? item);
  const [, monthNumber] = today.split('-').map(Number);
  const paymentTitle = items[0]?.recurring_payment.title;

  return (
    <>
      <div className="page-head">
        <h1>Оплаты</h1>
        <span className="muted">Сегодня {formatDate(today)}</span>
      </div>

      <section>
        <h2 className="section-title">Итоги за {MONTHS[monthNumber - 1].toLowerCase()}</h2>
        {summary.data && <SummaryCards summary={summary.data} />}
      </section>

      <section>
        <div className="toolbar">
          <div className="tabs" role="tablist">
            {TABS.map((tab) => (
              <button
                key={tab.state}
                role="tab"
                aria-selected={state === tab.state}
                className={`tab ${state === tab.state ? 'tab-active' : ''}`}
                onClick={() => update({ state: tab.state || null })}
              >
                {tab.label}
              </button>
            ))}
          </div>
          <select value={currency} onChange={(e) => update({ currency: e.target.value || null })} aria-label="Валюта">
            <option value="">Все валюты</option>
            {CURRENCIES.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </div>
        {paymentId && (
          <div className="chip">
            Платёж: {paymentTitle ?? `#${paymentId}`}
            <button className="btn btn-ghost btn-sm" onClick={() => update({ payment: null })} aria-label="Сбросить">
              ✕
            </button>
          </div>
        )}

        <ErrorBox error={list.error} />
        <div className="table-wrap">
          <table className={list.loading ? 'loading' : ''}>
            <thead>
              <tr>
                <th>Платёж</th>
                <th className="num">Сумма</th>
                <th>Срок</th>
                <th>Статус</th>
                <th>Дата оплаты</th>
                <th>Просрочка</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {items.map((o) => (
                <tr key={o.id} className={o.status === 'unpaid' && o.is_overdue ? 'row-danger' : ''}>
                  <td>
                    <Link to={`/?payment=${o.recurring_payment.id}`} className="link-plain">
                      {o.recurring_payment.title}
                    </Link>
                    {!o.recurring_payment.is_active && <span className="badge badge-muted badge-xs">удалён</span>}
                    {o.reminder_sent_at && (
                      <div className="hint" title={`Напоминание: ${formatDateTime(o.reminder_sent_at)}`}>
                        🔔 напомнили {formatDateTime(o.reminder_sent_at)}
                      </div>
                    )}
                  </td>
                  <td className="num">
                    {formatMoney(o.amount, o.currency)} <CurrencyTag currency={o.currency} />
                  </td>
                  <td>
                    <DueCell occurrence={o} today={today} />
                  </td>
                  <td>
                    <StatusBadge occurrence={o} />
                    {o.marked_by && <div className="hint">отметил {o.marked_by.username}</div>}
                  </td>
                  <td>{formatDate(o.paid_at)}</td>
                  <td>
                    <OverdueCell occurrence={o} />
                  </td>
                  <td>
                    <OccurrenceActions occurrence={o} onChanged={changed} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!list.loading && items.length === 0 && <Empty>Нет периодов по выбранным условиям</Empty>}
        </div>
        {list.data && (
          <Pager
            page={page}
            pageSize={PAGE_SIZE}
            count={list.data.count}
            onPage={(p) => update({ page: String(p) })}
          />
        )}
      </section>
    </>
  );
}
