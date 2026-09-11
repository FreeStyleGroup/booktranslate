import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { apiFetch, unauthorized, type CurrentUser } from "../lib/api";
import { currentUser } from "../lib/current-user";
import { accessToken, organizationId, renewUrl } from "../lib/session";
import { SignOut } from "../sign-out";
import "./cabinet.css";
import { SideNav, type NavCounts } from "./side-nav";
import { NavToggle } from "./nav-toggle";
import { ThemeToggle } from "../theme-toggle";

export const metadata: Metadata = {
  title: "Кабинет — BookTranslate",
  description: "Очередь замечаний, документы, терминология и расход.",
};

/** Числа рядом с разделами меню — из той же сводки, что и обзор. */
async function counts(): Promise<NavCounts | null> {
  const token = await accessToken();

  if (token === undefined) {
    return null;
  }

  try {
    return await apiFetch<NavCounts>("/overview", {
      token,
      organizationId: await organizationId(),
    });
  } catch (error) {
    if (unauthorized(error)) {
      redirect(renewUrl("/app"));
    }

    // Меню без чисел лучше кабинета, который не открылся.
    return null;
  }
}

/** Подпись под именем: своё пространство, а если его нет — почему. */
function workspaceLabel(me: CurrentUser | null): string {
  if (me === null) {
    return "Демонстрация";
  }

  return (
    me.memberships[0]?.organization_name ??
    (me.user.is_superuser ? "Администратор площадки" : "Без рабочего пространства")
  );
}

export default async function CabinetLayout({ children }: { children: ReactNode }) {
  const me = await currentUser("/app");
  // Сводка принадлежит организации: без неё API ответит отказом, и
  // спрашивать незачем.
  const navCounts = me === null || me.memberships.length === 0 ? null : await counts();
  const name = me?.user.full_name ?? me?.user.email ?? "Гость";
  const workspace = workspaceLabel(me);

  return (
    <div className="cab">
      <aside className="cab__side">
        <Link className="cab__brand" href="/">
          <span className="logo__mark" aria-hidden="true">
            📖
          </span>
          <span>
            BookTranslate<sup className="logo__ai">AI</sup>
          </span>
        </Link>

        <SideNav counts={navCounts} />
      </aside>

      <div className="cab__main">
        <header className="cab__top">
          <NavToggle />

          <div className="cab__search">
            <span aria-hidden="true">🔍</span>
            <span>Поиск по сегментам, терминам и документам</span>
          </div>

          <div className="cab__tools">
            <ThemeToggle />
            <button className="cab__icon" type="button" aria-label="Уведомления">
              <span aria-hidden="true">🔔</span>
            </button>

            <div className="cab__user">
              <span className="cab__avatar" aria-hidden="true">
                {name.slice(0, 1).toUpperCase()}
              </span>
              <span className="cab__who">
                <b>{name}</b>
                <span>{workspace}</span>
              </span>
            </div>

            <SignOut className="cab__exit" />
          </div>
        </header>

        <div className="cab__body">{children}</div>
      </div>
    </div>
  );
}
