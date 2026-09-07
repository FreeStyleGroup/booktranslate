"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/* Боковое меню кабинета.

   Разделы перечислены здесь, а не в разметке страницы: они одинаковы на
   всех экранах, и отмечать текущий вручную на каждом — верный способ
   однажды разойтись. */

type Item = { href: string; icon: string; label: string; count?: number };

const GROUPS: { title: string; items: Item[] }[] = [
  {
    title: "Работа",
    items: [
      { href: "/app", icon: "📊", label: "Обзор" },
      { href: "/app/queue", icon: "🧪", label: "Очередь замечаний", count: 128 },
      { href: "/app/documents", icon: "📚", label: "Документы", count: 7 },
      { href: "/app/projects", icon: "🗃", label: "Проекты", count: 3 },
    ],
  },
  {
    title: "Терминология",
    items: [
      { href: "/app/terms", icon: "🗂", label: "Термины книги", count: 24 },
      { href: "/app/catalog", icon: "🔍", label: "Каталог справок" },
      { href: "/app/glossary", icon: "📑", label: "Словарь" },
      { href: "/app/memory", icon: "🧠", label: "Память переводов" },
    ],
  },
  {
    title: "Организация",
    items: [
      { href: "/app/usage", icon: "💸", label: "Расход" },
      { href: "/app/team", icon: "👥", label: "Команда" },
      { href: "/app/settings", icon: "⚙️", label: "Настройки" },
    ],
  },
];

export function SideNav() {
  const pathname = usePathname();

  return (
    <>
      {GROUPS.map((group) => (
        <div className="cab__group" key={group.title}>
          <h4>{group.title}</h4>
          {group.items.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={
                // Точное совпадение для обзора, иначе он подсвечивался бы
                // на каждом вложенном разделе.
                pathname === item.href || (item.href !== "/app" && pathname.startsWith(item.href))
                  ? "cab__link is-active"
                  : "cab__link"
              }
            >
              <i aria-hidden="true">{item.icon}</i>
              <span>{item.label}</span>
              {item.count !== undefined && <span className="cab__count">{item.count}</span>}
            </Link>
          ))}
        </div>
      ))}
    </>
  );
}
