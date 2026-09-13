"use client";

/* Принятие приглашения: что нужно сделать зависит от того, кто открыл
   ссылку. Четыре случая, и у каждого своя кнопка — или её отсутствие.

   Подписи приходят готовым набором, а не выбираются здесь по языку: иначе
   в браузер уехали бы оба словаря целиком. */

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { fill } from "../i18n/config";
import type { Dictionary } from "../i18n/ru";
import type { Preview } from "../join-page";
import { SignOut } from "../sign-out";

const MIN_PASSWORD = 12;

export type JoinTexts = {
  join: Dictionary["join"];
  form: Dictionary["form"];
  /** Адрес страницы входа на том же языке. */
  loginHref: string;
  signIn: string;
};

export function JoinForm({
  token,
  preview,
  me,
  texts,
}: {
  token: string;
  preview: Preview;
  // Почта вошедшего. Пусто — ссылку открыл гость.
  me: string | null;
  texts: JoinTexts;
}) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const t = texts.join;

  async function accept(body: Record<string, unknown>): Promise<void> {
    setError(null);
    setBusy(true);

    try {
      const response = await fetch("/api/join", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, ...body }),
      });

      const payload = (await response.json()) as { error?: string; home?: string };

      if (!response.ok) {
        setError(payload.error ?? texts.form.failed);
        return;
      }

      // refresh() вместе с push(): кабинет собирается на сервере, и без
      // сброса кеша отрисовался бы по-старому — без нового пространства.
      router.push(payload.home ?? "/app");
      router.refresh();
    } catch {
      setError(texts.form.offline);
    } finally {
      setBusy(false);
    }
  }

  // Вошедший под другой почтой: приглашение не его, и принять его он не
  // может — выписано на конкретный ящик.
  if (me !== null && me !== preview.email) {
    return (
      <div className="sent" role="status">
        <span aria-hidden="true">🚪</span>
        <h2>{fill(t.wrongAccountTitle, { email: me })}</h2>
        <p>{fill(t.wrongAccountText, { email: preview.email })}</p>
        <SignOut className="btn btn--ghost" />
      </div>
    );
  }

  // Вошедший с той же почтой: одно нажатие.
  if (me !== null) {
    return (
      <div className="form">
        {error !== null && (
          <p className="form__error" role="alert">
            {error}
          </p>
        )}
        <button
          className="btn btn--primary"
          type="button"
          disabled={busy}
          onClick={() => void accept({})}
        >
          {busy ? texts.form.busy : t.accept}
          <i aria-hidden="true">↗</i>
        </button>
      </div>
    );
  }

  // Учётная запись есть, но в неё не вошли: пароль здесь не спрашивается —
  // ссылка из письма не должна открывать чужую учётную запись тому, кто её
  // перехватил. Вход — на своей странице, ссылка из письма подождёт.
  if (preview.has_account) {
    return (
      <div className="sent" role="status">
        <span aria-hidden="true">🔑</span>
        <h2>{t.hasAccountTitle}</h2>
        <p>{fill(t.hasAccountText, { email: preview.email })}</p>
        <a className="btn btn--primary" href={texts.loginHref}>
          {texts.signIn}
        </a>
      </div>
    );
  }

  function submit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();

    const form = new FormData(event.currentTarget);

    void accept({
      full_name: form.get("full_name"),
      password: form.get("password"),
    });
  }

  return (
    <form className="form" onSubmit={submit} noValidate>
      <label className="field">
        <span>{texts.form.name}</span>
        <input
          name="full_name"
          type="text"
          autoComplete="name"
          placeholder={texts.form.namePlaceholder}
        />
      </label>

      <label className="field">
        <span>{texts.form.email}</span>
        <input type="email" value={preview.email} readOnly autoComplete="email" />
        <small>{t.emailHint}</small>
      </label>

      <label className="field">
        <span>{texts.form.password}</span>
        <input
          name="password"
          type="password"
          required
          minLength={MIN_PASSWORD}
          autoComplete="new-password"
          placeholder={fill(texts.form.passwordHint, { n: MIN_PASSWORD })}
        />
      </label>

      {error !== null && (
        <p className="form__error" role="alert">
          {error}
        </p>
      )}

      <button className="btn btn--primary" type="submit" disabled={busy}>
        {busy ? texts.form.busy : t.acceptAndEnter}
        <i aria-hidden="true">↗</i>
      </button>
    </form>
  );
}
