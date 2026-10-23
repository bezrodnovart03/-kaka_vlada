import type { SummaryOut } from '../api/types';
import { formatMoney } from '../format';
import { CurrencyTag } from './ui';

/** Итоги отдельно по каждой валюте — без конвертации. */
export function SummaryCards({ summary }: { summary: SummaryOut }) {
  return (
    <div className="cards">
      {summary.totals.map((t) => (
        <div key={t.currency} className={`card ${t.count_planned === 0 ? 'card-dim' : ''}`}>
          <div className="card-head">
            <CurrencyTag currency={t.currency} />
            <span className="muted">{t.count_planned} к оплате</span>
          </div>
          <div className="card-total">{formatMoney(t.planned, t.currency)}</div>
          <dl className="card-rows">
            <div>
              <dt>Оплачено</dt>
              <dd className="text-ok">
                {formatMoney(t.paid, t.currency)} <small>({t.count_paid})</small>
              </dd>
            </div>
            <div>
              <dt>Осталось</dt>
              <dd>{formatMoney(t.unpaid, t.currency)}</dd>
            </div>
            <div>
              <dt>Просрочено</dt>
              <dd className={t.count_overdue ? 'text-danger' : ''}>
                {formatMoney(t.overdue, t.currency)} <small>({t.count_overdue})</small>
              </dd>
            </div>
          </dl>
        </div>
      ))}
    </div>
  );
}
