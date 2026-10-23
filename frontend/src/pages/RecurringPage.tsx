import { useState } from 'react';
import { Link } from 'react-router-dom';

import { ApiError } from '../api/client';
import { api } from '../api/endpoints';
import type { Currency, Period, RecurringPaymentIn, RecurringPaymentOut } from '../api/types';
import { useAuth } from '../auth';
import {
  CurrencyTag,
  Empty,
  ErrorBox,
  FieldError,
  Modal,
  Pager,
  useLoader,
  useToast,
} from '../components/ui';
import { CURRENCIES, formatDate, formatDateTime, formatMoney, PERIOD_LABEL } from '../format';

const PAGE_SIZE = 50;

export function RecurringPage() {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const [search, setSearch] = useState('');
  const [currency, setCurrency] = useState<Currency | ''>('');
  const [includeInactive, setIncludeInactive] = useState(false);
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);

  const list = useLoader(
    () =>
      api.recurring.list({
        search: search.trim() || undefined,
        currency: currency || undefined,
        include_inactive: includeInactive || undefined,
        page,
        page_size: PAGE_SIZE,
      }),
    [search, currency, includeInactive, page],
  );

  async function remove(payment: RecurringPaymentOut) {
    const ok = confirm(
      `Прекратить платёж «${payment.title}»?\n\nБудущие неоплаченные периоды и напоминания будут удалены, ` +
        'история оплат сохранится.',
    );
    if (!ok) return;
    try {
      await api.recurring.remove(payment.id);
      toast.ok(`Платёж «${payment.title}» прекращён`);
      list.reload();
    } catch (e) {
      toast.error(e);
    }
  }

  return (
    <>
      <div className="page-head">
        <h1>Регулярные платежи</h1>
        {isAdmin && (
          <button className="btn btn-primary" onClick={() => setCreating(true)}>
            + Добавить платёж
          </button>
        )}
      </div>

      <div className="toolbar">
        <input
          type="search"
          placeholder="Поиск по названию"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setPage(1);
          }}
        />
        <select
          value={currency}
          aria-label="Валюта"
          onChange={(e) => {
            setCurrency(e.target.value as Currency | '');
            setPage(1);
          }}
        >
          <option value="">Все валюты</option>
          {CURRENCIES.map((c) => (
            <option key={c}>{c}</option>
          ))}
        </select>
        <label className="check">
          <input type="checkbox" checked={includeInactive} onChange={(e) => setIncludeInactive(e.target.checked)} />
          Показывать удалённые
        </label>
      </div>

      <ErrorBox error={list.error} />
      <div className="table-wrap">
        <table className={list.loading ? 'loading' : ''}>
          <thead>
            <tr>
              <th>Название</th>
              <th className="num">Сумма</th>
              <th>Периодичность</th>
              <th>Ближайший неоплаченный срок</th>
              <th>Просрочено</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {list.data?.items.map((p) => (
              <tr key={p.id} className={p.is_active ? '' : 'row-muted'}>
                <td>
                  <Link to={`/?payment=${p.id}`} className="link-plain">
                    <strong>{p.title}</strong>
                  </Link>
                  {!p.is_active && (
                    <span className="badge badge-muted badge-xs" title={formatDateTime(p.deleted_at)}>
                      удалён
                    </span>
                  )}
                  {p.comment && <div className="hint">{p.comment}</div>}
                </td>
                <td className="num">
                  {formatMoney(p.amount, p.currency)} <CurrencyTag currency={p.currency} />
                </td>
                <td>
                  {PERIOD_LABEL[p.period]}
                  <div className="hint">{p.anchor_day}-го числа</div>
                </td>
                <td>
                  {p.next_occurrence ? (
                    <span className={p.next_occurrence.is_overdue ? 'text-danger' : ''}>
                      {formatDate(p.next_occurrence.due_date)}
                    </span>
                  ) : (
                    <span className="muted">—</span>
                  )}
                </td>
                <td>
                  {p.overdue_count > 0 ? (
                    <span className="badge badge-danger">{p.overdue_count}</span>
                  ) : (
                    <span className="muted">—</span>
                  )}
                </td>
                <td className="actions">
                  <Link className="btn btn-ghost btn-sm" to={`/?payment=${p.id}`}>
                    Периоды
                  </Link>
                  {isAdmin && p.is_active && (
                    <button className="btn btn-danger btn-sm" onClick={() => remove(p)}>
                      Удалить
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!list.loading && list.data?.items.length === 0 && (
          <Empty>{isAdmin ? 'Платежей пока нет — добавьте первый' : 'Платежей пока нет'}</Empty>
        )}
      </div>
      {list.data && <Pager page={page} pageSize={PAGE_SIZE} count={list.data.count} onPage={setPage} />}

      {creating && (
        <CreatePaymentDialog
          onClose={() => setCreating(false)}
          onCreated={(payment) => {
            setCreating(false);
            toast.ok(`Платёж «${payment.title}» добавлен`);
            list.reload();
          }}
        />
      )}
    </>
  );
}

function CreatePaymentDialog({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (payment: RecurringPaymentOut) => void;
}) {
  const { today } = useAuth();
  const toast = useToast();
  const [form, setForm] = useState<RecurringPaymentIn>({
    title: '',
    amount: '',
    currency: 'RUB',
    first_due_date: today,
    period: 'monthly',
    comment: '',
  });
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  const set = <K extends keyof RecurringPaymentIn>(key: K, value: RecurringPaymentIn[K]) =>
    setForm((f) => ({ ...f, [key]: value }));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const amount = form.amount.replace(/\s/g, '').replace(',', '.');
      onCreated(await api.recurring.create({ ...form, amount, comment: form.comment || null }));
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) setError(err);
      else toast.error(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="Новый регулярный платёж" onClose={onClose}>
      <form className="form" onSubmit={submit}>
        <label>
          Название
          <input
            autoFocus
            required
            maxLength={120}
            value={form.title}
            placeholder="Аренда офиса"
            onChange={(e) => set('title', e.target.value)}
          />
          <FieldError error={error} name="title" />
        </label>
        <div className="form-row">
          <label>
            Сумма
            <input
              required
              inputMode="decimal"
              placeholder="85000.00"
              value={form.amount}
              onChange={(e) => set('amount', e.target.value)}
            />
            <FieldError error={error} name="amount" />
          </label>
          <label>
            Валюта
            <select value={form.currency} onChange={(e) => set('currency', e.target.value as Currency)}>
              {CURRENCIES.map((c) => (
                <option key={c}>{c}</option>
              ))}
            </select>
            <FieldError error={error} name="currency" />
          </label>
        </div>
        <div className="form-row">
          <label>
            Дата ближайшей оплаты
            <input
              type="date"
              required
              value={form.first_due_date}
              onChange={(e) => set('first_due_date', e.target.value)}
            />
            <FieldError error={error} name="first_due_date" />
          </label>
          <label>
            Периодичность
            <select value={form.period} onChange={(e) => set('period', e.target.value as Period)}>
              {(Object.keys(PERIOD_LABEL) as Period[]).map((p) => (
                <option key={p} value={p}>
                  {PERIOD_LABEL[p]}
                </option>
              ))}
            </select>
          </label>
        </div>
        <label>
          Комментарий
          <textarea rows={2} value={form.comment ?? ''} onChange={(e) => set('comment', e.target.value)} />
        </label>
        <p className="hint">
          Если в месяце нет такого числа, срок переносится на последний день месяца. Если до срока 3 дня или меньше,
          напоминание в Telegram уйдёт сразу.
        </p>
        <div className="form-actions">
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Отмена
          </button>
          <button className="btn btn-primary" disabled={busy}>
            Добавить
          </button>
        </div>
      </form>
    </Modal>
  );
}
