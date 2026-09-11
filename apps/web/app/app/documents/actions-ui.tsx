"use client";

/* Кнопки книги: разобрать, разобрать заново, удалить.

   Клиентские, потому что у каждой есть состояние: пока идёт разбор, кнопку
   надо выключить, а отказ — показать рядом с ней, а не увести человека на
   страницу ошибки. Само действие при этом серверное — токен в браузер не
   попадает.

   Лежат рядом со списком, а не внутри карточки: удалять книгу приходится и
   из списка тоже — пробных загрузок бывает пять, и открывать ради каждой
   отдельную страницу незачем. */

import { useActionState } from "react";

import { deleteDocument, parseDocument, type Result } from "../actions";

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

/** Удаление книги.
 *
 * `icon` — вид для строки списка: там подпись «удалить» у каждой из
 * двадцати книг превращает список в столбец из одного слова. Вопрос
 * перед удалением одинаков в обоих видах: книга уходит вместе с разбором
 * и переводом, и это не та кнопка, которую жмут дважды подряд не глядя.
 */
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
          if (!confirm(`Удалить «${title}» вместе с разбором и переводом?`)) {
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
            title="Удалить книгу"
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

      {state.error !== undefined && (
        <p className="form__error" role="alert">
          {state.error}
        </p>
      )}
    </>
  );
}
