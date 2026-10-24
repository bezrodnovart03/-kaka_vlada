import { useRef, useState } from 'react';

import { ApiError } from '../api/client';
import { api } from '../api/endpoints';
import type { AttachmentOut, PaymentOccurrenceOut } from '../api/types';
import { useAuth } from '../auth';
import { formatDate, formatDateTime, formatMoney } from '../format';
import { Empty, ErrorBox, FieldError, Modal, useLoader, useToast } from './ui';

const ACCEPT = '.pdf,.png,.jpg,.jpeg,.webp,.heic,application/pdf,image/png,image/jpeg,image/webp,image/heic';

function formatSize(bytes: number | null): string {
  if (bytes === null) return '';
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} КБ`;
  return `${(bytes / 1024 / 1024).toFixed(1)} МБ`;
}

/** Чеки (файлы) и ссылки, прикреплённые к конкретному периоду оплаты. */
export function AttachmentsDialog({
  occurrence,
  onClose,
  onChanged,
}: {
  occurrence: PaymentOccurrenceOut;
  onClose: () => void;
  onChanged: () => void;
}) {
  const { me, isAdmin } = useAuth();
  const toast = useToast();
  const list = useLoader(() => api.attachments.list(occurrence.id), [occurrence.id]);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [uploadError, setUploadError] = useState<ApiError | null>(null);
  const [url, setUrl] = useState('');
  const [name, setName] = useState('');
  const [linkError, setLinkError] = useState<ApiError | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  function refresh() {
    list.reload();
    onChanged();
  }

  async function upload(files: FileList | null) {
    if (!files?.length) return;
    setBusy(true);
    setUploadError(null);
    let uploaded = 0;
    try {
      for (const file of Array.from(files)) {
        await api.attachments.uploadFile(occurrence.id, file);
        uploaded += 1;
      }
      toast.ok(uploaded === 1 ? 'Чек прикреплён' : `Прикреплено файлов: ${uploaded}`);
    } catch (e) {
      if (e instanceof ApiError && e.status === 422) setUploadError(e);
      else toast.error(e);
    } finally {
      setBusy(false);
      if (fileInput.current) fileInput.current.value = '';
      if (uploaded) refresh();
    }
  }

  async function addLink(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setLinkError(null);
    try {
      await api.attachments.addLink(occurrence.id, { url: url.trim(), name: name.trim() || undefined });
      setUrl('');
      setName('');
      setUploadError(null);
      toast.ok('Ссылка прикреплена');
      refresh();
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) setLinkError(err);
      else toast.error(err);
    } finally {
      setBusy(false);
    }
  }

  async function remove(attachment: AttachmentOut) {
    if (!confirm(`Удалить «${attachment.name}»?`)) return;
    setBusy(true);
    try {
      await api.attachments.remove(occurrence.id, attachment.id);
      toast.ok('Удалено');
      refresh();
    } catch (e) {
      toast.error(e);
    } finally {
      setBusy(false);
    }
  }

  async function downloadFile(attachment: AttachmentOut) {
    try {
      await api.attachments.download(occurrence.id, attachment);
    } catch (e) {
      toast.error(e);
    }
  }

  const items = list.data ?? [];

  return (
    <Modal title="Чеки и ссылки" onClose={onClose}>
      <p className="muted">
        {occurrence.recurring_payment.title} · {formatMoney(occurrence.amount, occurrence.currency)} · срок{' '}
        {formatDate(occurrence.due_date)}
      </p>

      <ErrorBox error={list.error} />
      {items.length > 0 ? (
        <ul className={`attachments ${list.loading ? 'loading' : ''}`}>
          {items.map((a) => (
            <li key={a.id} className="attachment">
              <span className="attachment-icon" aria-hidden>
                {a.kind === 'link' ? '🔗' : a.content_type === 'application/pdf' ? '📄' : '🖼️'}
              </span>
              <div className="attachment-body">
                {a.kind === 'link' && a.url ? (
                  <a href={a.url} target="_blank" rel="noopener noreferrer" className="attachment-name">
                    {a.name}
                  </a>
                ) : (
                  <button type="button" className="link-button attachment-name" onClick={() => downloadFile(a)}>
                    {a.name}
                  </button>
                )}
                <div className="hint">
                  {[formatSize(a.size), a.uploaded_by?.username, formatDateTime(a.created_at)]
                    .filter(Boolean)
                    .join(' · ')}
                </div>
              </div>
              {(isAdmin || a.uploaded_by?.id === me?.id) && (
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  disabled={busy}
                  onClick={() => remove(a)}
                  aria-label={`Удалить ${a.name}`}
                >
                  ✕
                </button>
              )}
            </li>
          ))}
        </ul>
      ) : (
        !list.loading && <Empty>Пока ничего не прикреплено</Empty>
      )}

      <div
        className={`dropzone ${dragging ? 'dropzone-active' : ''}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          void upload(e.dataTransfer.files);
        }}
      >
        <input
          ref={fileInput}
          type="file"
          accept={ACCEPT}
          multiple
          hidden
          onChange={(e) => void upload(e.target.files)}
        />
        <button
          type="button"
          className="btn btn-primary btn-sm"
          disabled={busy}
          onClick={() => fileInput.current?.click()}
        >
          {busy ? 'Загрузка…' : 'Выбрать файл'}
        </button>
        <span className="hint">или перетащите сюда · PDF, PNG, JPEG, WebP, HEIC</span>
        <FieldError error={uploadError} name="file" />
      </div>

      <form onSubmit={addLink} className="form">
        <label>
          Ссылка на чек или платёжку
          <input
            type="url"
            inputMode="url"
            placeholder="https://"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            required
            maxLength={2000}
          />
          <FieldError error={linkError} name="url" />
        </label>
        <label>
          <span>
            Название <span className="muted">(необязательно)</span>
          </span>
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={255} />
        </label>
        <div className="form-actions">
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Закрыть
          </button>
          <button className="btn btn-primary" disabled={busy || !url.trim()}>
            Прикрепить ссылку
          </button>
        </div>
      </form>
    </Modal>
  );
}
