import { useState } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';
import { login, session } from '../api/client';
import { useAction } from '../api/hooks';
import { ErrorNotice } from '../components/Common';

export function Login() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const action = useAction();
  const navigate = useNavigate();
  if (session.authenticated()) return <Navigate to="/projects" replace />;
  return <main className="mx-auto flex min-h-screen max-w-md items-center px-5 py-12">
    <section className="card w-full">
      <p className="text-sm font-bold text-indigo-600">◈ AGENTS FLOW</p>
      <h1>Вход в панель</h1><p className="muted">Проекты, агенты и решения по задачам.</p>
      <ErrorNotice message={action.error} />
      <form onSubmit={async event => {
        event.preventDefault();
        if (await action.run(() => login(email, password))) { setPassword(''); navigate('/projects', { replace: true }); }
      }}>
        <fieldset disabled={action.busy}>
          <label>Email<input type="email" autoComplete="username" required maxLength={254} value={email} onChange={e => setEmail(e.target.value)} /></label>
          <label>Пароль<input type="password" autoComplete="current-password" required maxLength={256} value={password} onChange={e => setPassword(e.target.value)} /></label>
          <button type="submit" className="w-full">{action.busy ? 'Вход…' : 'Войти'}</button>
        </fieldset>
      </form>
    </section>
  </main>;
}
