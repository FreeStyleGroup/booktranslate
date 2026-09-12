import type { Metadata } from "next";

import { AuthShell } from "../auth-shell";
import { ApiError, apiFetch } from "../lib/api";
import { currentUser } from "../lib/current-user";
import type { Role } from "../lib/work";
import { ROLE_LABEL } from "../app/labels";
import { JoinForm } from "./join-form";

export const metadata: Metadata = {
  title: "Приглашение — BookTranslate",
  description: "Принять приглашение в рабочее пространство.",
  // Страница открывается одноразовой ссылкой из письма — в поиске ей
  // делать нечего.
  robots: { index: false, follow: false },
};

/* Приглашение в рабочее пространство.

   Ссылка из письма ведёт сюда. Сначала показывается, куда и кем зовут, и
   только потом — что для этого нужно: вошедшему с той же почтой — одно
   нажатие, человеку без учётной записи — имя и пароль, а вошедшему под
   другой почтой — выйти. Ссылка уходит в API телом запроса, а не адресом:
   адрес попадает в журналы. */

export type Preview = {
  organization_name: string;
  email: string;
  role: Role;
  invited_by: string | null;
  expires_at: string;
  has_account: boolean;
};

const FOOTER = { text: "Уже работаете здесь?", href: "/login", link: "Войти" };

export default async function JoinPage({
  searchParams,
}: {
  searchParams: Promise<{ token?: string }>;
}) {
  const { token } = await searchParams;

  if (token === undefined || token === "") {
    return (
      <Shell title="Ссылка неполная" lead="В адресе нет ключа приглашения.">
        <p className="muted">
          Откройте ссылку из письма целиком — она длинная, и почтовые
          программы иногда переносят её на две строки.
        </p>
      </Shell>
    );
  }

  let preview: Preview;

  try {
    preview = await apiFetch<Preview>("/auth/invitations/lookup", {
      method: "POST",
      body: { token },
    });
  } catch (error) {
    const reason =
      error instanceof ApiError ? error.message : "Сервис недоступен. Попробуйте ещё раз через минуту.";

    return (
      <Shell title="Приглашение не открылось" lead={reason}>
        <p className="muted">
          Попросите того, кто вас пригласил, выписать приглашение заново — в
          разделе «Команда» его рабочего пространства.
        </p>
      </Shell>
    );
  }

  const me = await currentUser(`/join?token=${encodeURIComponent(token)}`);
  const role = (ROLE_LABEL[preview.role] ?? preview.role).toLowerCase();

  return (
    <Shell
      title={`Вас зовут в «${preview.organization_name}»`}
      lead={`${preview.invited_by ?? "Владелец пространства"} приглашает вас как ${role}. Приглашение на почту ${preview.email}.`}
    >
      <JoinForm token={token} preview={preview} me={me?.user.email ?? null} />
    </Shell>
  );
}

function Shell({
  title,
  lead,
  children,
}: {
  title: string;
  lead: string;
  children: React.ReactNode;
}) {
  return (
    <AuthShell title={title} lead={lead} footer={FOOTER}>
      {children}
    </AuthShell>
  );
}
