import { useEffect, useState } from 'react';
import { Navigate, NavLink, Outlet, Route, Routes, useNavigate } from 'react-router-dom';
import { logout, restoreSession, session } from './api/client';
import { Login } from './pages/Login';
import { Projects } from './pages/Projects';
import { Project } from './pages/Project';
import { Task } from './pages/Task';
import { Skills } from './pages/Skills';

function Layout() {
  const navigate = useNavigate();
  if (!session.authenticated()) return <Navigate to="/login" replace />;
  return <>
    <header className="border-b border-slate-800 bg-slate-950 text-white">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-6 px-5 py-4">
        <NavLink to="/projects" className="font-bold tracking-tight text-white">◈ Agents Flow</NavLink>
        <nav className="flex gap-4" aria-label="Главное меню">
          <NavLink to="/projects">Проекты</NavLink><NavLink to="/skills">Skills</NavLink>
        </nav>
        <button className="ml-auto secondary" onClick={async () => { await logout(); navigate('/login'); }}>Выйти</button>
      </div>
    </header>
    <main className="mx-auto max-w-7xl space-y-6 px-5 py-8"><Outlet /></main>
  </>;
}

export function App() {
  const [ready, setReady] = useState(session.authenticated());
  useEffect(() => {
    if (ready) return;
    let active = true;
    void restoreSession().catch(() => {}).finally(() => { if (active) setReady(true); });
    return () => { active = false; };
  }, [ready]);
  if (!ready) return <main aria-busy="true" />;
  return <Routes>
    <Route path="/login" element={<Login />} />
    <Route element={<Layout />}>
      <Route path="/projects" element={<Projects />} />
      <Route path="/projects/:id" element={<Project />} />
      <Route path="/tasks/:id" element={<Task />} />
      <Route path="/skills" element={<Skills />} />
      <Route path="/" element={<Navigate to="/projects" replace />} />
      <Route path="*" element={<section className="card"><h1>Страница не найдена</h1><NavLink to="/projects">К проектам</NavLink></section>} />
    </Route>
  </Routes>;
}
