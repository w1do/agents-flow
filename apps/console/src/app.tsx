import { useMemo, useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Link, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { createProjectsApi } from "@/api/projects";
import { Button } from "@/components/ui/button";
import { Login } from "./login";
import { ProjectsPage } from "./projects/projects-page";
import { EditorPage } from "./projects/editor-page";

function Session({
  token,
  onExit,
}: {
  token: string;
  onExit: (unauthorized?: boolean) => void;
}) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { retry: false, refetchOnWindowFocus: false },
          mutations: { retry: false },
        },
      }),
  );
  const api = useMemo(
    () =>
      createProjectsApi(token, () => {
        client.clear();
        onExit(true);
      }),
    [token, client, onExit],
  );
  return (
    <QueryClientProvider client={client}>
      <header className="border-b bg-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
          <Link to="/projects" className="font-semibold tracking-tight">
            Harness{" "}
            <span className="ml-2 text-sm font-normal text-muted-foreground">
              / консоль оператора
            </span>
          </Link>
          <Button
            variant="outline"
            onClick={() => {
              client.clear();
              onExit();
            }}
          >
            Выйти
          </Button>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-6 py-10">
        <Routes>
          <Route path="/projects" element={<ProjectsPage api={api} />} />
          <Route path="/projects/new" element={<EditorPage api={api} creating />} />
          <Route path="/projects/:projectId" element={<EditorPage api={api} />} />
          <Route path="*" element={<Navigate to="/projects" replace />} />
        </Routes>
      </main>
    </QueryClientProvider>
  );
}

export function App() {
  const [session, setSession] = useState<{ token: string } | null>(null);
  const [error, setError] = useState("");
  const navigate = useNavigate();
  if (!session)
    return (
      <Login
        error={error}
        onLogin={(token) => {
          setError("");
          setSession({ token });
          navigate("/projects", { replace: true });
        }}
      />
    );
  return (
    <Session
      token={session.token}
      onExit={(unauthorized) => {
        setSession((current) => (current === session ? null : current));
        if (unauthorized) setError("Токен не принят. Введите токен оператора заново.");
        navigate("/", { replace: true });
      }}
    />
  );
}
