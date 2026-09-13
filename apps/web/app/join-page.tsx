/* Приглашение в рабочее пространство — одна сборка на оба языка.

   Ссылка из письма ведёт сюда. Сначала показывается, куда и кем зовут, и
   только потом — что для этого нужно: вошедшему с той же почтой — одно
   нажатие, человеку без учётной записи — имя и пароль, а вошедшему под
   другой почтой — выйти. Ссылка уходит в API телом запроса, а не адресом:
   адрес попадает в журналы. */

import type { ReactNode } from "react";

import { AuthShell } from "./auth-shell";
import { dictionary, fill } from "./i18n";
import { localePath, type Locale } from "./i18n/config";
import { JoinForm } from "./join/join-form";
import { ApiError, apiFetch } from "./lib/api";
import { currentUser } from "./lib/current-user";
import type { Role } from "./lib/work";

export type Preview = {
  organization_name: string;
  email: string;
  role: Role;
  invited_by: string | null;
  expires_at: string;
  has_account: boolean;
};

export async function JoinPage({
  lang,
  searchParams,
}: {
  lang: Locale;
  searchParams: Promise<{ token?: string }>;
}) {
  const t = dictionary(lang);
  const { token } = await searchParams;

  // Ключ приглашения остаётся в адресе при смене языка: без него та же
  // страница на другом языке скажет «ссылка неполная».
  const path =
    token === undefined || token === "" ? "/join" : `/join?token=${encodeURIComponent(token)}`;

  const shell = (title: string, lead: string, children: ReactNode) => (
    <AuthShell
      lang={lang}
      path={path}
      title={title}
      lead={lead}
      footer={{
        text: t.join.footerText,
        href: localePath(lang, "/login"),
        link: t.join.footerLink,
      }}
    >
      {children}
    </AuthShell>
  );

  if (token === undefined || token === "") {
    return shell(
      t.join.noTokenTitle,
      t.join.noTokenLead,
      <p className="muted">{t.join.noTokenText}</p>,
    );
  }

  let preview: Preview;

  try {
    preview = await apiFetch<Preview>("/auth/invitations/lookup", {
      method: "POST",
      body: { token },
    });
  } catch (error) {
    // Отказ API приходит на языке API — по-русски. Английскому читателю он
    // непонятен, но врать про причину нельзя: общая фраза заменяет её
    // только там, где своей причины нет вовсе.
    const reason = error instanceof ApiError ? error.message : t.join.failedLead;

    return shell(t.join.failedTitle, reason, <p className="muted">{t.join.failedText}</p>);
  }

  const me = await currentUser(localePath(lang, `/join?token=${encodeURIComponent(token)}`));

  return shell(
    fill(t.join.title, { org: preview.organization_name }),
    fill(t.join.lead, {
      who: preview.invited_by ?? t.join.owner,
      role: t.roles[preview.role],
      email: preview.email,
    }),
    <JoinForm
      token={token}
      preview={preview}
      me={me?.user.email ?? null}
      texts={{
        join: t.join,
        form: t.form,
        loginHref: localePath(lang, "/login"),
        signIn: t.login.submit,
      }}
    />,
  );
}
