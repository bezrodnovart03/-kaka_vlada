import { useState } from 'react';

import { ApiError } from '../api/client';
import { api } from '../api/endpoints';
import type { PaymentOccurrenceOut } from '../api/types';
import { useAuth } from '../auth';
import { formatDate, formatMoney } from '../format';
import { AttachmentsDialog } from './AttachmentsDialog';
import { DateInput } from './DateInput';
import { FieldError, Modal, useToast } from './ui';

type Mode = 'pay' | 'correct' | 'attachments';

/**
 * Кнопки периода: «Оплачено», «Отменить», «Исправить дату», чеки и ссылки.
 * Доступны и админу, и пользователю.
 */
export function OccurrenceActions({
  occurrence,
  onChanged,
}: {
  occurrence: PaymentOccurrenceOut;
  onChanged: (updated: PaymentOccurrenceOut) => void;
}) {
  const toast = useToast();
  const [mode, setMode] = useState<Mode | null>(null);
  const [busy, setBusy] = useState(false);

  async function markPaidToday() {
    setBusy(true);
    try {
      const updated = await api.occurrences.patch(occurrence.id, { status: 'paid' });
      toast.ok(`«${occurrence.recurring_payment.title}» отмечен оплаченным`);
      onChanged(updated);
    } catch (e) {
      toast.error(e);
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    if (!confirm('Отменить отметку об оплате? Фактическая дата будет очищена.')) return;
    setBusy(true);
    try {
      const updated = await api.occurrences.patch(occurrence.id, { status: 'unpaid' });
      toast.ok('Отметка об оплате отменена');
      onChanged(updated);
    } catch (e) {
      toast.error(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="actions">
      {occurrence.status === 'unpaid' ? (
        <>
          <button className="btn btn-primary btn-sm" disabled={busy} onClick={markPaidToday}>
            Оплачено
          </button>
          <button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => setMode('pay')} title="Оплачено другой датой">
            Другой датой…
          </button>
        </>
      ) : (
        <>
          <button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => setMode('correct')}>
            Исправить дату
          </button>
          <button className="btn btn-ghost btn-sm" disabled={busy} onClick={cancel}>
            Отменить
          </button>
        </>
      )}
      <button
        className="btn btn-ghost btn-sm btn-count"
        onClick={() => setMode('attachments')}
        title="Чеки и ссылки"
        aria-label={`Чеки и ссылки: ${occurrence.attachments_count}`}
      >
        📎{occurrence.attachments_count > 0 && ` ${occurrence.attachments_count}`}
      </button>
      {mode === 'attachments' && (
        <AttachmentsDialog
          occurrence={occurrence}
          onClose={() => setMode(null)}
          onChanged={() => {
            api.occurrences.get(occurrence.id).then(onChanged, () => {});
          }}
        />
      )}
      {(mode === 'pay' || mode === 'correct') && (
        <PaidDateDialog
          mode={mode}
          occurrence={occurrence}
          onClose={() => setMode(null)}
          onSaved={(updated) => {
            setMode(null);
            onChanged(updated);
          }}
        />
      )}
    </div>
  );
}

function PaidDateDialog({
  mode,
  occurrence,
  onClose,
  onSaved,
}: {
  mode: 'pay' | 'correct';
  occurrence: PaymentOccurrenceOut;
  onClose: () => void;
  onSaved: (updated: PaymentOccurrenceOut) => void;
}) {
  const { today } = useAuth();
  const toast = useToast();
  const [paidAt, setPaidAt] = useState(occurrence.paid_at ?? today);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const updated = await api.occurrences.patch(
        occurrence.id,
        mode === 'pay' ? { status: 'paid', paid_at: paidAt } : { paid_at: paidAt },
      );
      toast.ok(updated.is_overdue ? 'Дата сохранена: оплата позже срока' : 'Дата сохранена: оплачено вовремя');
      onSaved(updated);
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) setError(err);
      else toast.error(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={mode === 'pay' ? 'Отметить оплату' : 'Исправить дату оплаты'} onClose={onClose}>
      <form onSubmit={submit} className="form">
        <p className="muted">
          {occurrence.recurring_payment.title} · {formatMoney(occurrence.amount, occurrence.currency)} · срок{' '}
          {formatDate(occurrence.due_date)}
        </p>
        <label>
          Фактическая дата оплаты
          <DateInput value={paidAt} max={today} today={today} onChange={setPaidAt} />
          <FieldError error={error} name="paid_at" />
        </label>
        <p className="hint">
          Срок оплаты не меняется. Оплата в день срока или раньше — вовремя, позже — просрочка.
        </p>
        <div className="form-actions">
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Отмена
          </button>
          <button className="btn btn-primary" disabled={busy}>
            Сохранить
          </button>
        </div>
      </form>
    </Modal>
  );
}
