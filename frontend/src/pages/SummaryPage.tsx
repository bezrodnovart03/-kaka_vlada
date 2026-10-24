import { useState } from 'react';

import { api } from '../api/endpoints';
import type { ISODate } from '../api/types';
import { useAuth } from '../auth';
import { DateInput } from '../components/DateInput';
import { SummaryCards } from '../components/SummaryCards';
import { ErrorBox, useLoader } from '../components/ui';
import { formatDate, monthBounds } from '../format';

type Preset = 'month' | 'next' | 'year' | 'to-date' | 'custom';

/** Итоги на дату и бюджет на месяц / год — один эндпоинт с разными диапазонами. */
export function SummaryPage() {
  const { today } = useAuth();
  const [preset, setPreset] = useState<Preset>('month');
  const [custom, setCustom] = useState<[ISODate, ISODate]>(monthBounds(today));

  const year = today.slice(0, 4);
  const ranges: Record<Exclude<Preset, 'custom'>, [ISODate, ISODate, string]> = {
    month: [...monthBounds(today), 'Текущий месяц'],
    next: [...monthBounds(today, 1), 'Следующий месяц'],
    year: [`${year}-01-01`, `${year}-12-31`, `Бюджет на ${year} год`],
    'to-date': [`${year}-01-01`, today, 'С начала года по сегодня'],
  };
  const [from, to] = preset === 'custom' ? custom : ranges[preset];

  const summary = useLoader(() => api.summary({ date_from: from, date_to: to }), [from, to]);

  return (
    <>
      <div className="page-head">
        <h1>Итоги и бюджет</h1>
      </div>
      <div className="toolbar">
        <div className="tabs">
          {(Object.keys(ranges) as Exclude<Preset, 'custom'>[]).map((key) => (
            <button key={key} className={`tab ${preset === key ? 'tab-active' : ''}`} onClick={() => setPreset(key)}>
              {ranges[key][2]}
            </button>
          ))}
          <button className={`tab ${preset === 'custom' ? 'tab-active' : ''}`} onClick={() => setPreset('custom')}>
            Свой период
          </button>
        </div>
        {preset === 'custom' && (
          <div className="range">
            <DateInput
              value={custom[0]}
              max={custom[1]}
              today={today}
              onChange={(value) => setCustom([value, custom[1]])}
              aria-label="С"
            />
            —
            <DateInput
              value={custom[1]}
              min={custom[0]}
              today={today}
              onChange={(value) => setCustom([custom[0], value])}
              aria-label="По"
            />
          </div>
        )}
      </div>

      <p className="muted">
        Период: {formatDate(from)} — {formatDate(to)}. Суммы считаются отдельно по каждой валюте, без конвертации.
      </p>
      <ErrorBox error={summary.error} />
      {summary.data && <SummaryCards summary={summary.data} />}
      <p className="hint">
        «К оплате» — все периоды со сроком в диапазоне, включая будущие по расписанию активных платежей. «Просрочено» —
        не оплачено, а срок уже прошёл.
      </p>
    </>
  );
}
