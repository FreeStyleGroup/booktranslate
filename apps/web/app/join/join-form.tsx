"use client";

/* Принятие приглашения: что нужно сделать зависит от того, кто открыл
   ссылку. Четыре случая, и у каждого своя кнопка — или её отсутствие. */

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { SignOut } from "../sign-out";
import type { Preview } from "./page";

const MIN_PASSWORD = 12;

export function JoinForm({
  token,
  preview,
  me,
}: {
  token: string;
  preview: Preview;
  // Почта вошедшего. Пусто — ссылку открыл гость.
  me: string | null;
}) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

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
        setError(payload.error ?? "Не получилось. Попробуйте ещё раз.");
        return;
      }

      // refresh() вместе с push(): кабинет собирается на сервере, и без
      // сброса кеша отрисовался бы по-старому — без нового пространства.
      router.push(payload.home ?? "/app");
      router.refresh();
    } catch {
      setError("Сеть недоступна. Проверьте соединение.");
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
        <h2>Вы вошли как {me}</h2>
        <p>
          Приглашение выписано на {preview.email}. Выйдите и откройте ссылку
          снова — под той почтой, на которую оно пришло.
        </p>
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
          {busy ? "Секунду…" : "Принять приглашение"}
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
        <h2>У вас уже есть учётная запись</h2>
        <p>
          Войдите под почтой {preview.email} и откройте ссылку из письма ещё
          раз — приглашение примется одним нажатием.
        </p>
        <a className="btn btn--primary" href="/login">
          Войти
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
        <span>Как вас зовут</span>
        <input name="full_name" type="text" autoComplete="name" placeholder="Анна Петрова" />
      </label>

      <label className="field">
        <span>Почта</span>
        <input type="email" value={preview.email} readOnly autoComplete="email" />
        <small>На неё выписано приглашение — сменить её здесь нельзя.</small>
      </label>

      <label className="field">
        <span>Пароль</span>
        <input
          name="password"
          type="password"
          required
          minLength={MIN_PASSWORD}
          autoComplete="new-password"
          placeholder={`Не короче ${MIN_PASSWORD} знаков`}
        />
      </label>

      {error !== null && (
        <p className="form__error" role="alert">
          {error}
        </p>
      )}

      <button className="btn btn--primary" type="submit" disabled={busy}>
        {busy ? "Секунду…" : "Принять и войти"}
        <i aria-hidden="true">↗</i>
      </button>
    </form>
  );
}
