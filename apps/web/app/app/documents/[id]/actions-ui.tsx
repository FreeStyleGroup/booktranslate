"use client";

/* Кнопки карточки документа: разобрать, разобрать заново, удалить.

   Клиентские, потому что у каждой есть состояние: пока идёт разбор, кнопку
   надо выключить, а отказ — показать рядом с ней, а не увести человека на
   страницу ошибки. Само действие при этом серверное — токен в браузер не
   попадает. */

import { useActionState } from "react";

import { deleteDocument, parseDocument, type Result } from "../../actions";

const EMPTY: Result = {};

/* Размер передаётся снаружи: в строке действий кнопки стоят рядом с
   ссылкой на исходник, и полноразмерная кнопка рядом с уменьшенной сразу
   выдаёт себя разной высотой. Один ряд — один размер. */
export function ParseButton({
  id,
  again,
  label,
  small,
}: {
  id: string;
  again?: boolean;
  label: string;
  small?: boolean;
}) {
  const [state, action, busy] = useActionState(parseDocument, EMPTY);
  const size = small === true ? " btn--small" : "";

  return (
    <>
      <form action={action} className="wk-inline">
        <input type="hidden" name="id" value={id} />
        {again === true && <input type="hidden" name="force" value="yes" />}

        <button
          className={(again === true ? "btn btn--ghost" : "btn btn--primary") + size}
          type="submit"
          disabled={busy}
        >
          {busy ? "Разбираем…" : label}
        </button>
      </form>

      {state.error !== undefined && (
        <p className="form__error" role="alert">
          {state.error}
        </p>
      )}
    </>
  );
}

export function DeleteButton({
  id,
  title,
  small,
}: {
  id: string;
  title: string;
  small?: boolean;
}) {
  const [state, action, busy] = useActionState(deleteDocument, EMPTY);

  return (
    <>
      <form
        action={action}
        className="wk-inline"
        onSubmit={(event) => {
          // Удаление книги уносит с собой сегменты и перевод — это не та
          // кнопка, которую нажимают дважды подряд без вопроса.
          if (!confirm(`Удалить «${title}» вместе с разбором и переводом?`)) {
            event.preventDefault();
          }
        }}
      >
        <input type="hidden" name="id" value={id} />

        <button
          className={"btn btn--ghost wk-danger" + (small === true ? " btn--small" : "")}
          type="submit"
          disabled={busy}
        >
          {busy ? "Удаляем…" : "Удалить"}
        </button>
      </form>

      {state.error !== undefined && (
        <p className="form__error" role="alert">
          {state.error}
        </p>
      )}
    </>
  );
}
