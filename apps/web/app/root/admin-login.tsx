"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

/* Вход в раздел управления доступом.

   Форма та же, что у всех, и это намеренно: отдельного «входа для
   администратора» с отдельным паролем не бывает — бывает учётная запись с
   правами. Ответ на неверные данные тоже общий: раздел не подсказывает,
   существует ли он для того, кто в него стучится. */

export function AdminLogin({ unreachable = false }: { unreachable?: boolean }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setError(null);
    setBusy(true);

    const form = new FormData(event.currentTarget);

    try {
      const response = await fetch("/api/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: form.get("email"),
          password: form.get("password"),
        }),
      });

      if (!response.ok) {
        const payload = (await response.json()) as { error?: string };

        setError(payload.error ?? "Не получилось войти");
        return;
      }

      router.refresh();
    } catch {
      setError("Сеть недоступна. Проверьте соединение.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="root-login">
      <form className="root-login__card form" onSubmit={submit} noValidate>
        <span className="root-login__mark" aria-hidden="true">
          🛡️
        </span>
        <h1>Управление доступом</h1>
        <p className="muted">
          {unreachable
            ? "API не отвечает — список пользователей сейчас недоступен."
            : "Раздел для администратора площадки."}
        </p>

        <label className="field">
          <span>Почта</span>
          <input name="email" type="email" required autoComplete="email" />
        </label>

        <label className="field">
          <span>Пароль</span>
          <input name="password" type="password" required autoComplete="current-password" />
        </label>

        {error !== null && (
          <p className="form__error" role="alert">
            {error}
          </p>
        )}

        <button className="btn btn--primary" type="submit" disabled={busy}>
          {busy ? "Секунду…" : "Войти"}
        </button>
      </form>
    </div>
  );
}
