"use client";

import { useActionState } from "react";

import { changeStatus, type Result } from "./actions";

/* Кнопка смены состояния доступа.

   Клиентский компонент ради одного: показать отказ. Серверное действие
   возвращает ошибку, а прочитать её из формы серверного компонента
   нельзя — нужен `useActionState`. У каждой кнопки своё состояние, поэтому
   отказ появляется под той кнопкой, которую нажали. */

const EMPTY: Result = {};

export function StatusForm({
  id,
  status,
  label,
  primary = false,
}: {
  id: string;
  status: "active" | "suspended";
  label: string;
  primary?: boolean;
}) {
  const [state, action, busy] = useActionState(changeStatus, EMPTY);

  return (
    <form className="adm-status" action={action}>
      <input type="hidden" name="id" value={id} />
      <input type="hidden" name="status" value={status} />
      <button
        className={primary ? "btn btn--primary btn--small" : "btn btn--ghost btn--small"}
        type="submit"
        disabled={busy}
      >
        {busy ? "Секунду…" : label}
      </button>
      {state.error !== undefined && (
        <small className="adm-status__error" role="alert">
          {state.error}
        </small>
      )}
    </form>
  );
}
