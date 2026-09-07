"use client";

import { useActionState } from "react";

import { createUser, type CreateState } from "./actions";

/* Заведение учётной записи администратором.

   Пароль генерируется на сервере и показывается здесь один раз: в базе
   только хеш, и второй раз показать его будет неоткуда. Поэтому он выведен
   крупно и отдельно — чтобы его скопировали сразу, а не «потом». */

const EMPTY: CreateState = {};

export function CreateUser() {
  const [state, action, busy] = useActionState(createUser, EMPTY);

  return (
    <section className="adm-panel">
      <div className="adm-panel__head">
        <h2>Создать пользователя</h2>
        <span className="muted">Пароль сгенерируется — покажем его один раз</span>
      </div>

      <form className="adm-create" action={action}>
        <label className="field">
          <span>Почта</span>
          <input name="email" type="email" required placeholder="colleague@company.ru" />
        </label>

        <label className="field">
          <span>Имя</span>
          <input name="full_name" type="text" placeholder="Анна Петрова" />
        </label>

        <label className="field">
          <span>Рабочее пространство</span>
          <input name="organization_name" type="text" required placeholder="Бюро переводов" />
        </label>

        <label className="field">
          <span>Роль</span>
          <select name="role" defaultValue="owner">
            <option value="owner">Владелец</option>
            <option value="admin">Администратор</option>
            <option value="manager">Менеджер</option>
            <option value="translator">Переводчик</option>
            <option value="reviewer">Редактор</option>
            <option value="viewer">Наблюдатель</option>
          </select>
        </label>

        <button className="btn btn--primary" type="submit" disabled={busy}>
          {busy ? "Создаём…" : "Создать"}
        </button>
      </form>

      {state.error !== undefined && (
        <p className="form__error" role="alert">
          {state.error}
        </p>
      )}

      {state.created !== undefined && (
        <div className="secret" role="status">
          <div>
            <b>{state.created.email}</b>
            <span className="muted"> · {state.created.organization}</span>
          </div>
          <code>{state.created.password}</code>
          <span className="muted">
            Передайте пароль лично. Второй раз он не покажется — в базе только хеш.
          </span>
        </div>
      )}
    </section>
  );
}
