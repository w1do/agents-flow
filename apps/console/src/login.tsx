import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export function Login({
  error,
  onLogin,
}: {
  error: string;
  onLogin: (token: string) => void;
}) {
  const [token, setToken] = useState("");
  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <section className="panel w-full max-w-md p-8">
        <p className="eyebrow">Harness / Operator console</p>
        <h1 className="mb-3">Вход</h1>
        <p className="mb-7 text-sm text-muted-foreground">
          Введите токен оператора. После перезагрузки вкладки потребуется войти снова.
        </p>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (token.trim()) {
              onLogin(token.trim());
              setToken("");
            }
          }}
          className="space-y-5"
        >
          <div className="space-y-2">
            <label htmlFor="operator-token">Токен оператора</label>
            <Input
              id="operator-token"
              type="password"
              autoComplete="off"
              autoCapitalize="none"
              spellCheck={false}
              value={token}
              onChange={(event) => setToken(event.target.value)}
              required
            />
          </div>
          {error && (
            <p className="error-box" role="alert">
              {error}
            </p>
          )}
          <Button className="w-full" type="submit" disabled={!token.trim()}>
            Войти
          </Button>
        </form>
      </section>
    </main>
  );
}
