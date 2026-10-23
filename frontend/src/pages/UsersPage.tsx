import { useState } from 'react';

import { ApiError } from '../api/client';
import { api } from '../api/endpoints';
import type { UserOut, UserPatchIn } from '../api/types';
import { Empty, ErrorBox, FieldError, Modal, Pager, useLoader, useToast } from '../components/ui';
import { formatDateTime } from '../format';

const PAGE_SIZE = 50;

export function UsersPage() {
  const toast = useToast();
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<UserOut | 'new' | null>(null);
  const list = useLoader(() => api.users.list({ page, page_size: PAGE_SIZE }), [page]);

  async function toggleActive(user: UserOut) {
    try {
      await api.users.patch(user.id, { is_active: !user.is_active });
      toast.ok(user.is_active ? `${user.username} заблокирован` : `${user.username} разблокирован`);
      list.reload();
    } catch (e) {
      toast.error(e);
    }
  }

  async function remove(user: UserOut) {
    if (!confirm(`Удалить пользователя ${user.username}? Его отметки об оплате сохранятся.`)) return;
    try {
      await api.users.remove(user.id);
      toast.ok(`Пользователь ${user.username} удалён`);
      list.reload();
    } catch (e) {
      toast.error(e);
    }
  }

  return (
    <>
      <div className="page-head">
        <h1>Пользователи</h1>
        <button className="btn btn-primary" onClick={() => setEditing('new')}>
          + Добавить пользователя
        </button>
      </div>
      <ErrorBox error={list.error} />
      <div className="table-wrap">
        <table className={list.loading ? 'loading' : ''}>
          <thead>
            <tr>
              <th>Логин</th>
              <th>Имя</th>
              <th>Email</th>
              <th>Роль</th>
              <th>Последний вход</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {list.data?.items.map((u) => {
              const locked = u.is_env_admin || u.role === 'admin';
              return (
                <tr key={u.id} className={u.is_active ? '' : 'row-muted'}>
                  <td>
                    <strong>{u.username}</strong>
                    {!u.is_active && <span className="badge badge-danger badge-xs">заблокирован</span>}
                  </td>
                  <td>{[u.first_name, u.last_name].filter(Boolean).join(' ') || <span className="muted">—</span>}</td>
                  <td>{u.email || <span className="muted">—</span>}</td>
                  <td>
                    {u.role === 'admin' ? (
                      <span className="badge badge-ok">Администратор{u.is_env_admin ? ' (.env)' : ''}</span>
                    ) : (
                      <span className="badge badge-muted">Пользователь</span>
                    )}
                  </td>
                  <td>{u.last_login ? formatDateTime(u.last_login) : <span className="muted">не входил</span>}</td>
                  <td className="actions">
                    {locked ? (
                      <span className="hint">управляется через .env</span>
                    ) : (
                      <>
                        <button className="btn btn-ghost btn-sm" onClick={() => setEditing(u)}>
                          Изменить
                        </button>
                        <button className="btn btn-ghost btn-sm" onClick={() => toggleActive(u)}>
                          {u.is_active ? 'Заблокировать' : 'Разблокировать'}
                        </button>
                        <button className="btn btn-danger btn-sm" onClick={() => remove(u)}>
                          Удалить
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {!list.loading && list.data?.items.length === 0 && <Empty>Пользователей нет</Empty>}
      </div>
      {list.data && <Pager page={page} pageSize={PAGE_SIZE} count={list.data.count} onPage={setPage} />}

      {editing && (
        <UserDialog
          user={editing === 'new' ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={(u, created) => {
            setEditing(null);
            toast.ok(created ? `Пользователь ${u.username} создан` : 'Изменения сохранены');
            list.reload();
          }}
        />
      )}
    </>
  );
}

function UserDialog({
  user,
  onClose,
  onSaved,
}: {
  user: UserOut | null;
  onClose: () => void;
  onSaved: (user: UserOut, created: boolean) => void;
}) {
  const toast = useToast();
  const [form, setForm] = useState({
    username: user?.username ?? '',
    password: '',
    email: user?.email ?? '',
    first_name: user?.first_name ?? '',
    last_name: user?.last_name ?? '',
  });
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (key: keyof typeof form, value: string) => setForm((f) => ({ ...f, [key]: value }));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      if (user) {
        const patch: UserPatchIn = {
          username: form.username,
          email: form.email,
          first_name: form.first_name,
          last_name: form.last_name,
        };
        if (form.password) patch.password = form.password;
        onSaved(await api.users.patch(user.id, patch), false);
      } else {
        onSaved(await api.users.create(form), true);
      }
    } catch (err) {
      if (err instanceof ApiError && (err.status === 422 || err.status === 409)) setError(err);
      else toast.error(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={user ? `Пользователь ${user.username}` : 'Новый пользователь'} onClose={onClose}>
      <form className="form" onSubmit={submit}>
        <label>
          Логин
          <input autoFocus required maxLength={150} value={form.username} onChange={(e) => set('username', e.target.value)} />
          <FieldError error={error} name="username" />
        </label>
        <label>
          {user ? 'Новый пароль (оставьте пустым, чтобы не менять)' : 'Пароль'}
          <input
            type="password"
            autoComplete="new-password"
            required={!user}
            minLength={8}
            maxLength={128}
            value={form.password}
            onChange={(e) => set('password', e.target.value)}
          />
          <FieldError error={error} name="password" />
        </label>
        <div className="form-row">
          <label>
            Имя
            <input value={form.first_name} onChange={(e) => set('first_name', e.target.value)} />
          </label>
          <label>
            Фамилия
            <input value={form.last_name} onChange={(e) => set('last_name', e.target.value)} />
          </label>
        </div>
        <label>
          Email
          <input type="email" value={form.email} onChange={(e) => set('email', e.target.value)} />
          <FieldError error={error} name="email" />
        </label>
        <p className="hint">Через панель создаются только обычные пользователи. Роль администратора задаётся в .env.</p>
        <div className="form-actions">
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Отмена
          </button>
          <button className="btn btn-primary" disabled={busy}>
            {user ? 'Сохранить' : 'Создать'}
          </button>
        </div>
      </form>
    </Modal>
  );
}
