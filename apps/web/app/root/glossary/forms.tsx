"use client";

/* Кнопки ленты словарей: «просмотрено» и «снять из общего».

   Клиентские ради одного — показать отказ под той кнопкой, которую нажали.
   Тот же приём, что у смены состояния доступа. */

import { useActionState } from "react";

import { markReviewed, removeShared, type Result } from "../actions";

const EMPTY: Result = {};

export function ReviewedForm({ upload, reviewed }: { upload: string; reviewed: boolean }) {
  const [state, action, busy] = useActionState(markReviewed, EMPTY);

  if (reviewed) {
    return null;
  }

  return (
    <form className="adm-status" action={action}>
      <input type="hidden" name="upload" value={upload} />
      <button className="btn btn--ghost btn--small" type="submit" disabled={busy}>
        {busy ? "Секунду…" : "Просмотрено"}
      </button>
      {state.error !== undefined && (
        <small className="adm-status__error" role="alert">
          {state.error}
        </small>
      )}
    </form>
  );
}

export function RemoveSharedForm({ id, term }: { id: string; term: string }) {
  const [state, action, busy] = useActionState(removeShared, EMPTY);

  return (
    <form
      className="adm-status"
      action={action}
      onSubmit={(event) => {
        if (!confirm(`Снять «${term}» из общего словаря?`)) {
          event.preventDefault();
        }
      }}
    >
      <input type="hidden" name="id" value={id} />
      <button className="btn btn--ghost btn--small" type="submit" disabled={busy}>
        {busy ? "Секунду…" : "Снять"}
      </button>
      {state.error !== undefined && (
        <small className="adm-status__error" role="alert">
          {state.error}
        </small>
      )}
    </form>
  );
}
