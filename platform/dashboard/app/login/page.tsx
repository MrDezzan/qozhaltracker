"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { getBrowserSupabase } from "../../lib/supabaseBrowser";
import { describeAuthError } from "../../lib/auth";
import { Button } from "../../components/ui/Button";

export default function LoginPage() {
  const router = useRouter();
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);

    // Клиент вводит логин вида ferma-k3n7q2; полный адрес можно
    // ввести целиком — тогда домен не дописывается.
    const domain = process.env.NEXT_PUBLIC_LOGIN_DOMAIN || "livestock.local";
    const email = login.includes("@") ? login.trim() : `${login.trim()}@${domain}`;

    const { error } = await getBrowserSupabase().auth.signInWithPassword({
      email,
      password,
    });

    setBusy(false);
    if (error) {
      setError(describeAuthError(error.message));
      return;
    }
    router.push("/");
    router.refresh();
  }

  const inputClass =
    "w-full border border-line rounded-lg px-3.5 py-2.5 text-sm bg-surface placeholder:text-faint transition-shadow focus:outline-none focus:ring-4 focus:ring-brand/5 focus:border-brand";

  return (
    <main className="min-h-screen flex items-center justify-center px-4">
      <div className="w-full max-w-[360px]">
        <div className="mb-8">
          <h1 className="text-xl font-medium text-ink tracking-tight">
            Qozhal
          </h1>
          <p className="text-sm text-muted mt-1.5">
            Логин и пароль выданы при установке оборудования
          </p>
        </div>

        <div className="bg-surface border border-line rounded-xl px-6 py-6">
          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <label htmlFor="login" className="block text-sm font-medium text-muted mb-2">
                Логин
              </label>
              <input
                id="login"
                required
                autoComplete="username"
                value={login}
                onChange={(e) => setLogin(e.target.value)}
                placeholder="ferma-k3n7q2"
                className={inputClass}
              />
            </div>
            <div>
              <label
                htmlFor="password"
                className="block text-sm font-medium text-muted mb-2"
              >
                Пароль
              </label>
              <input
                id="password"
                type="password"
                required
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className={inputClass}
              />
            </div>
            <Button type="submit" disabled={busy} className="w-full">
              {busy ? "Вход…" : "Войти"}
            </Button>
            {error && <p className="text-sm text-trouble">{error}</p>}
          </form>
        </div>

        <p className="text-sm text-faint text-center mt-6">
          Забыли пароль? Обратитесь в техническую поддержку.
        </p>
      </div>
    </main>
  );
}
