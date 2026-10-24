import { Navigate, NavLink, Outlet, Route, Routes } from 'react-router-dom';

import { useAuth } from './auth';
import { CalendarPage } from './pages/CalendarPage';
import { LoginPage } from './pages/LoginPage';
import { OccurrencesPage } from './pages/OccurrencesPage';
import { RecurringPage } from './pages/RecurringPage';
import { SummaryPage } from './pages/SummaryPage';
import { UsersPage } from './pages/UsersPage';

function Layout() {
  const { me, isAdmin, signOut } = useAuth();
  const name = [me?.first_name, me?.last_name].filter(Boolean).join(' ') || me?.username;
  return (
    <div className="layout">
      <header className="topbar">
        <div className="brand">🧾 Invoice Keeper</div>
        <nav className="nav">
          <NavLink to="/" end>
            Оплаты
          </NavLink>
          <NavLink to="/recurring">Регулярные платежи</NavLink>
          <NavLink to="/calendar">Календарь</NavLink>
          <NavLink to="/summary">Итоги</NavLink>
          {/* Только UX: права проверяет бэкенд. */}
          {isAdmin && <NavLink to="/users">Пользователи</NavLink>}
          {/* Django-админка: журнал изменений, доставки напоминаний, логи. Вход — тем же логином. */}
          {isAdmin && (
            <a href="/admin/" target="_blank" rel="noopener">
              Django-админка ↗
            </a>
          )}
        </nav>
        <div className="userbox">
          <span>
            {name}
            <span className="hint">{isAdmin ? 'администратор' : 'пользователь'}</span>
          </span>
          <button className="btn btn-ghost btn-sm" onClick={signOut}>
            Выйти
          </button>
        </div>
      </header>
      <main className="content">
        <Outlet />
      </main>
    </div>
  );
}

export function App() {
  const { me, ready, isAdmin } = useAuth();
  if (!ready) return <div className="splash">Загрузка…</div>;
  if (!me) return <LoginPage />;
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<OccurrencesPage />} />
        <Route path="recurring" element={<RecurringPage />} />
        <Route path="calendar" element={<CalendarPage />} />
        <Route path="summary" element={<SummaryPage />} />
        {isAdmin && <Route path="users" element={<UsersPage />} />}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
