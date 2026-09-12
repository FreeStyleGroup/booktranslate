"use client";

/* Роль в пространстве и правка учётной записи — в строке списка.

   Роль меняется списком на месте: выбор уходит сразу, отказ показывается
   под ним. Правка почты и имени раскрывается по кнопке: два поля на каждой
   из двухсот строк превратили бы список в анкету. */

import { useActionState, useState, useTransition } from "react";

import { ROLE_HINT, ROLE_LABEL } from "../app/labels";
import { changeMemberRole, updateUser, type EditState } from "./actions";

const ROLES = ["owner", "admin", "manager", "translator", "reviewer", "viewer"];
const EMPTY: EditState = {};

export function RoleSelect({
  userId,
  organizationId,
  role,
  label,
}: {
  userId: string;
  organizationId: string;
  role: string;
  label: string;
}) {
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();

  return (
    <span className="adm-role">
      <select
        className="adm-role__select"
        value={role}
        disabled={pending}
        aria-label={`Роль в пространстве ${label}`}
        onChange={(event) => {
          const next = event.target.value;

          setError(null);
          start(async () => {
            const result = await changeMemberRole(userId, organizationId, next);

            if (result.error !== undefined) {
              setError(result.error);
            }
          });
        }}
      >
        {ROLES.map((item) => (
          <option key={item} value={item} title={ROLE_HINT[item]}>
            {ROLE_LABEL[item]}
          </option>
        ))}
      </select>
      {error !== null && (
        <small className="adm-status__error" role="alert">
          {error}
        </small>
      )}
    </span>
  );
}

export function EditUser({
  id,
  email,
  fullName,
}: {
  id: string;
  email: string;
  fullName: string | null;
}) {
  const [open, setOpen] = useState(false);
  const [state, action, busy] = useActionState(updateUser, EMPTY);

  if (!open) {
    return (
      <button className="btn btn--ghost btn--small" type="button" onClick={() => setOpen(true)}>
        Изменить
      </button>
    );
  }

  return (
    <form key={state.at ?? 0} className="adm-edit" action={action}>
      <input type="hidden" name="id" value={id} />
      <input
        name="full_name"
        type="text"
        defaultValue={fullName ?? ""}
        placeholder="Имя"
        aria-label="Имя"
        maxLength={200}
      />
      <input
        name="email"
        type="email"
        defaultValue={email}
        required
        aria-label="Почта"
        maxLength={320}
      />
      <span className="adm-edit__actions">
        <button className="btn btn--primary btn--small" type="submit" disabled={busy}>
          {busy ? "Секунду…" : "Сохранить"}
        </button>
        <button
          className="btn btn--ghost btn--small"
          type="button"
          disabled={busy}
          onClick={() => setOpen(false)}
        >
          Готово
        </button>
      </span>
      {state.error !== undefined && (
        <small className="adm-status__error" role="alert">
          {state.error}
        </small>
      )}
      {state.at !== undefined && state.error === undefined && (
        <small className="adm-edit__ok" role="status">
          Записано
        </small>
      )}
    </form>
  );
}
