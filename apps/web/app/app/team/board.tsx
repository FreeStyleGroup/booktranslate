"use client";

/* Команда рабочего пространства.

   Три плитки: пригласить, кто уже здесь, кого ждут. Управление видно
   только тем, кому оно разрешено, — владельцу и администратору; остальные
   видят состав команды без кнопок, а не кнопки, отвечающие отказом.

   Про ссылку приглашения. Она показывается один раз, сразу после выписки:
   в базе лежит её хеш, и второй раз показать её неоткуда. Если почта
   площадки не настроена или письмо не дошло, это сказано рядом с
   ссылкой — и ссылку передают сами. В списке ожидающих ссылки уже нет:
   там можно только отозвать приглашение или выписать заново. */

import { useActionState, useState, useTransition } from "react";

import type { Invitation, Member, Role, Team } from "../../lib/work";
import { ROLE_HINT, ROLE_LABEL, plural, when } from "../labels";
import {
  changeRole,
  inviteMember,
  removeMember,
  revokeInvitation,
  type InviteResult,
} from "./actions";

const EMPTY: InviteResult = {};

// Порядок ролей в выборе — от широких прав к узким. Владелец в списке
// есть, но выбрать его может только владелец: так же отвечает API.
const ROLES: Role[] = ["owner", "admin", "manager", "translator", "reviewer", "viewer"];

/** Кому разрешено распоряжаться составом. */
function manages(role: Role): boolean {
  return role === "owner" || role === "admin";
}

export function TeamBoard({ team, me }: { team: Team; me: string | null }) {
  const manage = manages(team.my_role);
  const owner = team.my_role === "owner";

  return (
    <>
      {manage && <Invite owner={owner} />}
      <Members members={team.members} me={me} manage={manage} owner={owner} />
      {team.invitations.length > 0 && (
        <Invitations invitations={team.invitations} manage={manage} />
      )}
    </>
  );
}

function Invite({ owner }: { owner: boolean }) {
  const [state, action, busy] = useActionState(inviteMember, EMPTY);

  return (
    <section className="tile tm-block">
      <div className="tile__head">
        <h3>Пригласить в команду</h3>
        <span className="tile__note">ссылка действует неделю</span>
      </div>

      <p className="tile__note st-lead">
        Человек получит письмо со ссылкой и войдёт сразу — одобрение площадки
        ему не нужно: за него ручаетесь вы. Если у него уже есть учётная
        запись, пространство добавится к его списку.
      </p>

      <form key={state.at ?? 0} action={action} className="tm-invite">
        <label className="field">
          <span>Почта</span>
          <input
            name="email"
            type="email"
            required
            maxLength={320}
            placeholder="kollega@company.ru"
            autoComplete="off"
          />
        </label>

        <RoleSelect name="role" defaultValue="translator" owner={owner} />

        <button className="btn btn--primary" type="submit" disabled={busy}>
          {busy ? "Выписываем…" : "Пригласить"}
        </button>
      </form>

      {state.error !== undefined && (
        <p className="form__error" role="alert">
          {state.error}
        </p>
      )}

      {state.invited !== undefined && <Issued invited={state.invited} />}
    </section>
  );
}

/** Только что выписанное приглашение: ссылка и судьба письма. */
function Issued({ invited }: { invited: NonNullable<InviteResult["invited"]> }) {
  const [copied, setCopied] = useState(false);

  async function copy(): Promise<void> {
    try {
      await navigator.clipboard.writeText(invited.link);
      setCopied(true);
    } catch {
      // Буфер обмена недоступен (не HTTPS, запрет браузера): ссылка и так
      // на экране, её можно выделить руками.
    }
  }

  return (
    <div className="tm-issued" role="status">
      <p>
        <b>{invited.invitation.email}</b> — приглашение выписано, роль:{" "}
        {ROLE_LABEL[invited.invitation.role] ?? invited.invitation.role}.
      </p>

      <p className={invited.email_sent ? "st-state is-ok" : "st-state"}>
        {invited.email_sent
          ? `Письмо отправлено: ${invited.email_detail}.`
          : `Письмо не ушло: ${invited.email_detail}. Передайте ссылку сами — она ниже.`}
      </p>

      {/* Ссылка видна один раз: в базе только её хеш. */}
      <div className="tm-link">
        <code>{invited.link}</code>
        <button className="btn btn--ghost btn--small" type="button" onClick={() => void copy()}>
          {copied ? "Скопировано" : "Скопировать"}
        </button>
      </div>

      <p className="tile__note">
        Ссылка показывается только сейчас: потом её можно лишь выписать заново.
      </p>
    </div>
  );
}

function RoleSelect({
  name,
  defaultValue,
  owner,
  onChange,
  disabled,
  label,
}: {
  name: string;
  defaultValue: Role;
  owner: boolean;
  onChange?: (role: Role) => void;
  disabled?: boolean;
  label?: string;
}) {
  return (
    <label className="field">
      <span>{label ?? "Роль"}</span>
      <select
        name={name}
        defaultValue={defaultValue}
        disabled={disabled}
        onChange={onChange === undefined ? undefined : (event) => onChange(event.target.value as Role)}
      >
        {ROLES.filter((role) => owner || role !== "owner").map((role) => (
          <option key={role} value={role}>
            {ROLE_LABEL[role]} — {ROLE_HINT[role]}
          </option>
        ))}
      </select>
    </label>
  );
}

function Members({
  members,
  me,
  manage,
  owner,
}: {
  members: Member[];
  me: string | null;
  manage: boolean;
  owner: boolean;
}) {
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();

  function run(action: () => Promise<{ error?: string }>): void {
    setError(null);
    start(async () => {
      const result = await action();

      if (result.error !== undefined) {
        setError(result.error);
      }
    });
  }

  return (
    <section className="tile tm-block">
      <div className="tile__head">
        <h3>Участники</h3>
        <span className="tile__note">
          {members.length} {plural(members.length, "человек", "человека", "человек")}
        </span>
      </div>

      {error !== null && (
        <p className="form__error" role="alert">
          {error}
        </p>
      )}

      <div className="tm-list">
        {members.map((member) => {
          const self = member.email === me;
          // Владельца трогает только владелец; себя не трогает никто —
          // так же отвечает API, и кнопки, ведущие к отказу, не рисуются.
          const editable = manage && !self && (owner || member.role !== "owner");

          return (
            <div className="tm-row" key={member.user_id}>
              <span className="tm-avatar" aria-hidden="true">
                {(member.full_name ?? member.email).slice(0, 1).toUpperCase()}
              </span>

              <span className="tm-who">
                <b>
                  {member.full_name ?? member.email}
                  {self && <span className="tile__note"> · это вы</span>}
                </b>
                <span className="tile__note">
                  {member.email} ·{" "}
                  {member.last_login_at === null
                    ? "ещё не заходил"
                    : `заходил ${when(member.last_login_at)}`}
                </span>
              </span>

              {editable ? (
                <RoleSelect
                  name={`role-${member.user_id}`}
                  label={`Роль: ${member.full_name ?? member.email}`}
                  defaultValue={member.role}
                  owner={owner}
                  disabled={pending}
                  onChange={(role) => run(() => changeRole(member.user_id, role))}
                />
              ) : (
                <span className="chip chip--info tm-role">{ROLE_LABEL[member.role]}</span>
              )}

              {editable && (
                <button
                  className="wk-kill"
                  type="button"
                  disabled={pending}
                  aria-label={`Убрать из команды: ${member.email}`}
                  title="Убрать из команды"
                  onClick={() => {
                    if (confirm(`Убрать ${member.email} из команды? Учётная запись останется.`)) {
                      run(() => removeMember(member.user_id));
                    }
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
              )}
            </div>
          );
        })}
      </div>

      {manage && (
        <p className="tile__note wk-seg__foot">
          Свою роль не меняют и себя не удаляют: единственный владелец,
          понизивший себя, оставил бы пространство без хозяина. Владельца
          назначает и снимает только владелец.
        </p>
      )}
    </section>
  );
}

function Invitations({ invitations, manage }: { invitations: Invitation[]; manage: boolean }) {
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();

  return (
    <section className="tile tm-block">
      <div className="tile__head">
        <h3>Ждут ответа</h3>
        <span className="tile__note">выписанные приглашения</span>
      </div>

      {error !== null && (
        <p className="form__error" role="alert">
          {error}
        </p>
      )}

      <div className="tm-list">
        {invitations.map((invitation) => (
          <div className="tm-row tm-row--waiting" key={invitation.id}>
            <span className="tm-avatar" aria-hidden="true">
              ✉
            </span>

            <span className="tm-who">
              <b>{invitation.email}</b>
              <span className="tile__note">
                {ROLE_LABEL[invitation.role] ?? invitation.role}
                {invitation.invited_by !== null && ` · пригласил ${invitation.invited_by}`}
                {" · "}
                {invitation.expired ? (
                  <span className="tm-expired">срок истёк</span>
                ) : (
                  `действует до ${when(invitation.expires_at)}`
                )}
              </span>
            </span>

            {manage && (
              <button
                className="btn btn--ghost btn--small"
                type="button"
                disabled={pending}
                onClick={() => {
                  setError(null);
                  start(async () => {
                    const result = await revokeInvitation(invitation.id);

                    if (result.error !== undefined) {
                      setError(result.error);
                    }
                  });
                }}
              >
                Отозвать
              </button>
            )}
          </div>
        ))}
      </div>

      {manage && (
        <p className="tile__note wk-seg__foot">
          Ссылку второй раз не показать — в базе лежит только её отпечаток.
          Если письмо потерялось или срок истёк, пригласите ту же почту
          заново: прежняя ссылка перестанет действовать.
        </p>
      )}
    </section>
  );
}
