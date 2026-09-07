"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/* Боковое меню кабинета.

   Разделы перечислены здесь, а не в разметке страницы: они одинаковы на
   всех экранах, и отмечать текущий вручную на каждом — верный способ
   однажды разойтись. */

type Item = { href: string; icon: string; label: string; count?: number };

/** Числа рядом с разделами — те же, что на обзоре. */
export type NavCounts = {
  flagged: number;
  documents: number;
  projects: number;
  undecided_terms: number;
};

function groups(counts: NavCounts | null): { title: string; items: Item[] }[] {
  return [
    {
      title: "Работа",
      items: [
        { href: "/app", icon: "📊", label: "Обзор" },
        {
          href: "/app/queue",
          icon: "🧪",
          label: "Очередь замечаний",
          count: counts?.flagged,
        },
        { href: "/app/documents", icon: "📚", label: "Документы", count: counts?.documents },
        { href: "/app/projects", icon: "🗃", label: "Проекты", count: counts?.projects },
      ],
    },
    {
      title: "Терминология",
      items: [
        {
          href: "/app/terms",
          icon: "🗂",
          label: "Термины книги",
          count: counts?.undecided_terms,
        },
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
}

export function SideNav({ counts }: { counts: NavCounts | null }) {
  const pathname = usePathname();

  return (
    <>
      {groups(counts).map((group) => (
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
              {item.count !== undefined && item.count > 0 && (
                <span className="cab__count">{item.count.toLocaleString("ru-RU")}</span>
              )}
            </Link>
          ))}
        </div>
      ))}
    </>
  );
}
