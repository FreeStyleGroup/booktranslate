"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

/* Форма входа и регистрации.

   Одна на два случая: поля различаются двумя строками, а поведение —
   ничем. Две почти одинаковые формы разъезжаются на первой же правке. */

const MIN_PASSWORD = 12;

export function AuthForm({ mode }: { mode: "login" | "register" }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);

  const register = mode === "register";

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
          mode,
          email: form.get("email"),
          password: form.get("password"),
          full_name: form.get("full_name"),
          organization_name: form.get("organization_name"),
        }),
      });

      const payload = (await response.json()) as {
        error?: string;
        pending?: boolean;
        home?: string;
      };

      if (!response.ok) {
        setError(payload.error ?? "Не получилось. Попробуйте ещё раз.");
        return;
      }

      // Регистрация никуда не ведёт: она заявка, и доступ по ней открывает
      // администратор. Отправить человека в кабинет, из которого его
      // выставят, — худшее, что тут можно сделать.
      if (payload.pending === true) {
        setSent(true);
        return;
      }

      // refresh() нужен вместе с push(): кабинет собирается на сервере и
      // без сброса кеша отрисовался бы по старому — без сеанса. Адрес
      // назначения приходит от сервера: администратора площадки ведут в
      // управление доступом, остальных — в кабинет.
      router.push(payload.home ?? "/app");
      router.refresh();
    } catch {
      setError("Сеть недоступна. Проверьте соединение.");
    } finally {
      setBusy(false);
    }
  }

  if (sent) {
    return (
      <div className="sent" role="status">
        <span aria-hidden="true">📬</span>
        <h2>Заявка отправлена</h2>
        <p>
          Доступ открывает администратор. Как только заявку одобрят, вы
          войдёте той же почтой и паролем — на странице входа.
        </p>
      </div>
    );
  }

  return (
    <form className="form" onSubmit={submit} noValidate>
      {register && (
        <label className="field">
          <span>Как вас зовут</span>
          <input name="full_name" type="text" autoComplete="name" placeholder="Анна Петрова" />
        </label>
      )}

      <label className="field">
        <span>Почта</span>
        <input
          name="email"
          type="email"
          required
          autoComplete="email"
          placeholder="you@company.ru"
        />
      </label>

      <label className="field">
        <span>Пароль</span>
        <input
          name="password"
          type="password"
          required
          minLength={register ? MIN_PASSWORD : 1}
          autoComplete={register ? "new-password" : "current-password"}
          placeholder={register ? `Не короче ${MIN_PASSWORD} знаков` : "Ваш пароль"}
        />
      </label>

      {register && (
        <label className="field">
          <span>Рабочее пространство</span>
          <input
            name="organization_name"
            type="text"
            required
            placeholder="Бюро переводов «Пример»"
          />
          <small>
            Проекты, словари и каталог терминов принадлежат ему. Коллег
            пригласите позже.
          </small>
        </label>
      )}

      {error !== null && (
        <p className="form__error" role="alert">
          {error}
        </p>
      )}

      <button className="btn btn--primary" type="submit" disabled={busy}>
        {busy ? "Секунду…" : register ? "Создать рабочее пространство" : "Войти"}
        <i aria-hidden="true">↗</i>
      </button>
    </form>
  );
}
