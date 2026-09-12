"use client";

/* Удаление проекта.

   Необратимо и уносит книги с переводами, поэтому крестик стоит в углу
   карточки, подальше от рабочей кнопки, а подтверждение спрашивается
   окном с числом книг. Память переводов при этом остаётся — она
   принадлежит пространству, и об этом сказано в окне: иначе человек не
   решится удалить проект, боясь потерять накопленное.

   Без права удалять кнопка не рисуется: кнопка, ведущая к отказу, хуже
   её отсутствия. */

import { useState, useTransition } from "react";

import { deleteProject } from "../actions";
import { ConfirmDialog } from "../confirm-dialog";
import { plural, thousands } from "../labels";

export function DeleteProject({ id, name, books }: { id: string; name: string; books: number }) {
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();

  function remove(): void {
    setError(null);
    start(async () => {
      const result = await deleteProject(id);

      if (result.error !== undefined) {
        setError(result.error);
        return;
      }

      setOpen(false);
    });
  }

  return (
    <>
      <button
        className="wk-kill"
        type="button"
        aria-label={`Удалить проект ${name}`}
        title="Удалить проект"
        onClick={() => {
          setError(null);
          setOpen(true);
        }}
      >
        <svg viewBox="0 0 24 24" aria-hidden="true" width="16" height="16">
          <path
            d="M6 6l12 12M18 6L6 18"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
          />
        </svg>
      </button>

      <ConfirmDialog
        open={open}
        title={`Удалить проект «${name}»?`}
        confirmLabel="Удалить проект"
        busyLabel="Удаляем…"
        busy={pending}
        error={error}
        onConfirm={remove}
        onCancel={() => setOpen(false)}
      >
        {books === 0 ? (
          <p>Книг в нём нет. Отменить удаление будет нельзя.</p>
        ) : (
          <>
            <p>
              Вместе с ним удалятся {thousands(books)} {plural(books, "книга", "книги", "книг")} с
              переводами и замечаниями. Отменить это будет нельзя.
            </p>
            <p>
              Память переводов останется: она принадлежит пространству, и следующая книга той же
              языковой пары возьмёт из неё готовые переводы.
            </p>
          </>
        )}
      </ConfirmDialog>
    </>
  );
}
