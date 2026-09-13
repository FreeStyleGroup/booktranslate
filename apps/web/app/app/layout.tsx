import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { CONTACT_EMAIL } from "../contacts";
import { dictionary } from "../i18n";
import { apiFetch, unauthorized, type CurrentUser } from "../lib/api";
import { currentUser } from "../lib/current-user";
import { accessToken, organizationId, renewUrl } from "../lib/session";
import { SignOut } from "../sign-out";
import "./cabinet.css";
import { Bell } from "./bell";
import { SideNav, type NavCounts } from "./side-nav";
import { NavToggle } from "./nav-toggle";
import { ThemeToggle } from "../theme-toggle";

export const metadata: Metadata = {
  title: "Кабинет — BookTranslate",
  description: "Очередь замечаний, документы, терминология и расход.",
  // Кабинет за входом: поисковику здесь нечего показать, кроме страницы
  // входа, и незачем ходить по адресам, которые ему всё равно откажут.
  robots: { index: false, follow: false },
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
        {/* Логотип ведёт на обзор, а не на главную сайта: вошедший
            остаётся в кабинете, витрина ему сейчас не нужна. */}
        <Link className="cab__brand" href="/app">
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

          {/* Обычная форма, а не клиентский компонент: результаты живут на
              своей странице, и Enter ведёт туда без единой строки скрипта.
              На узком экране остаётся значок — ссылка на ту же страницу. */}
          <form className="cab__search" action="/app/search" method="get" role="search">
            <Link href="/app/search" aria-label="Поиск">
              🔍
            </Link>
            <input
              type="search"
              name="query"
              placeholder="Поиск по книгам, терминам, справкам и тексту"
              aria-label="Поиск по кабинету"
              minLength={2}
              maxLength={200}
              autoComplete="off"
            />
          </form>

          <div className="cab__tools">
            <ThemeToggle />
            {/* Задания пространства: без пространства спрашивать не о чем. */}
            <Bell active={me !== null && me.memberships.length > 0} />

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

        {/* Подвал есть и здесь, а не только на главной: кабинет — тоже
            страница сайта, и человеку, который провёл в нём час, некуда
            написать, если что-то пошло не так. */}
        <footer className="cab__foot">
          {/* Кабинет пока только на русском: витрина переведена, разделы
              за входом — следующая работа. Подпись берётся из словаря
              явно, чтобы это было видно в коде, а не подразумевалось. */}
          <span>BookTranslate · {dictionary("ru").meta.tagline}</span>
          <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>
        </footer>
      </div>
    </div>
  );
}
