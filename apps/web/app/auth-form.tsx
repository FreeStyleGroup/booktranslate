"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { fill } from "./i18n/config";
import type { Dictionary } from "./i18n/ru";

/* Форма входа и регистрации.

   Одна на два случая: поля различаются двумя строками, а поведение —
   ничем. Две почти одинаковые формы разъезжаются на первой же правке.

   🔥 Тексты приходят готовым набором, а не выбираются здесь по языку.
   Иначе в браузер уехали бы оба словаря целиком — и английский посетитель
   скачивал бы русскую страницу вместе со своей. */

const MIN_PASSWORD = 12;

export type AuthTexts = {
  form: Dictionary["form"];
  submit: string;
  /** Экран «заявка отправлена». У входа его нет — там сразу кабинет. */
  sent: { title: string; text: string } | null;
};

export function AuthForm({ mode, texts }: { mode: "login" | "register"; texts: AuthTexts }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);

  const register = mode === "register";
  const t = texts.form;

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
        setError(payload.error ?? t.failed);
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
      setError(t.offline);
    } finally {
      setBusy(false);
    }
  }

  if (sent && texts.sent !== null) {
    return (
      <div className="sent" role="status">
        <span aria-hidden="true">📬</span>
        <h2>{texts.sent.title}</h2>
        <p>{texts.sent.text}</p>
      </div>
    );
  }

  return (
    <form className="form" onSubmit={submit} noValidate>
      {register && (
        <label className="field">
          <span>{t.name}</span>
          <input name="full_name" type="text" autoComplete="name" placeholder={t.namePlaceholder} />
        </label>
      )}

      <label className="field">
        <span>{t.email}</span>
        <input
          name="email"
          type="email"
          required
          autoComplete="email"
          placeholder={t.emailPlaceholder}
        />
      </label>

      <label className="field">
        <span>{t.password}</span>
        <input
          name="password"
          type="password"
          required
          minLength={register ? MIN_PASSWORD : 1}
          autoComplete={register ? "new-password" : "current-password"}
          placeholder={register ? fill(t.passwordHint, { n: MIN_PASSWORD }) : t.passwordPlaceholder}
        />
      </label>

      {register && (
        <label className="field">
          <span>{t.workspace}</span>
          <input
            name="organization_name"
            type="text"
            required
            placeholder={t.workspacePlaceholder}
          />
          <small>{t.workspaceHint}</small>
        </label>
      )}

      {error !== null && (
        <p className="form__error" role="alert">
          {error}
        </p>
      )}

      <button className="btn btn--primary" type="submit" disabled={busy}>
        {busy ? t.busy : texts.submit}
        <i aria-hidden="true">↗</i>
      </button>
    </form>
  );
}
