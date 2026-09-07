import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";

import { apiFetch, type CurrentUser } from "../lib/api";
import { accessToken } from "../lib/session";
import "./cabinet.css";
import { SideNav } from "./side-nav";
import { ThemeToggle } from "./theme-toggle";

export const metadata: Metadata = {
  title: "Кабинет — BookTranslate",
  description: "Очередь замечаний, документы, терминология и расход.",
};

/** Кто вошёл — или никто, если сеанса нет либо API недоступен. */
async function currentUser(): Promise<CurrentUser | null> {
  const token = await accessToken();

  if (token === undefined) {
    return null;
  }

  try {
    return await apiFetch<CurrentUser>("/auth/me", { token });
  } catch {
    // Просроченный токен или недоступный API — не повод показать пустой
    // экран: кабинет откроется с пометкой, что это демонстрация.
    return null;
  }
}

export default async function CabinetLayout({ children }: { children: ReactNode }) {
  const me = await currentUser();
  const name = me?.user.full_name ?? me?.user.email ?? "Гость";
  const workspace = me?.memberships[0]?.organization_name ?? "Демонстрация";

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

        <SideNav />
      </aside>

      <div className="cab__main">
        <header className="cab__top">
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
          </div>
        </header>

        <div className="cab__body">{children}</div>
      </div>
    </div>
  );
}
