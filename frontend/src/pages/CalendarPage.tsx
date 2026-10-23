import { useState } from 'react';

import { api } from '../api/endpoints';
import type { PaymentOccurrenceOut } from '../api/types';
import { useAuth } from '../auth';
import { OccurrenceActions } from '../components/OccurrenceActions';
import { SummaryCards } from '../components/SummaryCards';
import { ErrorBox, Modal, StatusBadge, useLoader } from '../components/ui';
import { formatDate, formatMoney, monthBounds, MONTHS } from '../format';

const WEEKDAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];

/** Календарь оплат: периоды на сетке месяца + итоги месяца по валютам. */
export function CalendarPage() {
  const { today } = useAuth();
  const [offset, setOffset] = useState(0);
  const [from, to] = monthBounds(today, offset);
  const [selected, setSelected] = useState<PaymentOccurrenceOut | null>(null);

  const occurrences = useLoader(
    () => api.occurrences.list({ due_from: from, due_to: to, page_size: 200 }),
    [from],
  );
  const summary = useLoader(() => api.summary({ date_from: from, date_to: to }), [from]);

  const [year, month] = from.split('-').map(Number);
  const daysInMonth = Number(to.slice(8, 10));
  const firstWeekday = (new Date(Date.UTC(year, month - 1, 1)).getUTCDay() + 6) % 7;
  const byDay = new Map<number, PaymentOccurrenceOut[]>();
  for (const o of occurrences.data?.items ?? []) {
    const day = Number(o.due_date.slice(8, 10));
    byDay.set(day, [...(byDay.get(day) ?? []), o]);
  }

  const cells: (number | null)[] = [
    ...Array<null>(firstWeekday).fill(null),
    ...Array.from({ length: daysInMonth }, (_, i) => i + 1),
  ];
  while (cells.length % 7) cells.push(null);

  return (
    <>
      <div className="page-head">
        <h1>Календарь оплат</h1>
        <div className="month-nav">
          <button className="btn btn-ghost" onClick={() => setOffset(offset - 1)} aria-label="Предыдущий месяц">
            ←
          </button>
          <strong>
            {MONTHS[month - 1]} {year}
          </strong>
          <button className="btn btn-ghost" onClick={() => setOffset(offset + 1)} aria-label="Следующий месяц">
            →
          </button>
          {offset !== 0 && (
            <button className="btn btn-ghost btn-sm" onClick={() => setOffset(0)}>
              Сегодня
            </button>
          )}
        </div>
      </div>

      <ErrorBox error={occurrences.error} />
      <div className={`calendar ${occurrences.loading ? 'loading' : ''}`}>
        {WEEKDAYS.map((d) => (
          <div key={d} className="cal-weekday">
            {d}
          </div>
        ))}
        {cells.map((day, i) => {
          const iso = day ? `${from.slice(0, 8)}${String(day).padStart(2, '0')}` : '';
          return (
            <div key={i} className={`cal-cell ${!day ? 'cal-empty' : ''} ${iso === today ? 'cal-today' : ''}`}>
              {day && <div className="cal-day">{day}</div>}
              {day &&
                (byDay.get(day) ?? []).map((o) => (
                  <button
                    key={o.id}
                    className={`cal-item ${o.status === 'paid' ? 'cal-paid' : o.is_overdue ? 'cal-overdue' : 'cal-unpaid'}`}
                    onClick={() => setSelected(o)}
                    title={`${o.recurring_payment.title} — ${formatMoney(o.amount, o.currency)}`}
                  >
                    <span className="cal-title">{o.recurring_payment.title}</span>
                    <span className="cal-amount">{formatMoney(o.amount, o.currency)}</span>
                  </button>
                ))}
            </div>
          );
        })}
      </div>
      <p className="hint">
        Будущие месяцы в итогах учитывают плановые платежи по расписанию, даже если периоды ещё не созданы.
      </p>

      <section>
        <h2 className="section-title">
          Итоги за {MONTHS[month - 1].toLowerCase()} {year}
        </h2>
        {summary.data && <SummaryCards summary={summary.data} />}
      </section>

      {selected && (
        <Modal title={selected.recurring_payment.title} onClose={() => setSelected(null)}>
          <dl className="details">
            <dt>Сумма</dt>
            <dd>{formatMoney(selected.amount, selected.currency)}</dd>
            <dt>Срок</dt>
            <dd>{formatDate(selected.due_date)}</dd>
            <dt>Статус</dt>
            <dd>
              <StatusBadge occurrence={selected} />
            </dd>
            <dt>Дата оплаты</dt>
            <dd>{formatDate(selected.paid_at)}</dd>
          </dl>
          <OccurrenceActions
            occurrence={selected}
            onChanged={(updated) => {
              setSelected(updated);
              occurrences.reload();
              summary.reload();
            }}
          />
        </Modal>
      )}
    </>
  );
}
