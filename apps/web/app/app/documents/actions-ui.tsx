"use client";

/* Удаление файла.

   Клиентская кнопка, потому что у неё есть состояние: пока идёт запрос, её надо
   выключить, а отказ — показать рядом, а не страницей ошибки. Само действие при этом
   серверное. */

import { useActionState } from "react";

import { deleteDocument, type Result } from "../actions";
import { ReportError } from "../ui/toast";

const EMPTY: Result = {};

/** Удаление файла. `icon` — вид для строки списка. */
export function DeleteButton({
  id,
  title,
  small,
  icon,
}: {
  id: string;
  title: string;
  small?: boolean;
  icon?: boolean;
}) {
  const [state, action, busy] = useActionState(deleteDocument, EMPTY);

  return (
    <>
      <form
        action={action}
        className="wk-inline"
        onSubmit={(event) => {
          if (!confirm(`Удалить файл «${title}»? Книга, в которую он входит, останется без него.`)) {
            event.preventDefault();
          }
        }}
      >
        <input type="hidden" name="id" value={id} />

        {icon === true ? (
          <button
            className="wk-kill"
            type="submit"
            disabled={busy}
            aria-label={`Удалить «${title}»`}
            title="Удалить файл"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true" width="16" height="16">
              <path
                d="M4 7h16M10 7V5h4v2M6 7l1 13h10l1-13M10 11v6M14 11v6"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.7"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
        ) : (
          <button
            className={"btn btn--ghost wk-danger" + (small === true ? " btn--small" : "")}
            type="submit"
            disabled={busy}
          >
            {busy ? "Удаляем…" : "Удалить"}
          </button>
        )}
      </form>

      <ReportError error={state.error} at={state} />
    </>
  );
}
