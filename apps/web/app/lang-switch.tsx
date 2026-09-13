"use client";

/* Переключатель языка.

   Переводит на тот же адрес, а не на главную: человек, переключивший язык
   на регистрации, должен остаться на регистрации. Возврат на главную —
   самая частая ошибка языковых переключателей и самая раздражающая.

   Ссылками, а не кнопками с переходом: адрес второго языка существует, и
   его надо дать браузеру — чтобы открывалось в новой вкладке, копировалось
   из контекстного меню и виделось поисковиком как обычная ссылка. */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useRef, useState } from "react";

import { LOCALES, localeOf, switchPath, type Locale } from "./i18n/config";
import { useDismiss } from "./use-dismiss";

const TITLES: Record<Locale, { short: string; title: string }> = {
  ru: { short: "RU", title: "Русский" },
  en: { short: "EN", title: "English" },
};

export function LangSwitch({
  label,
  className = "top__theme",
}: {
  label: string;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const pathname = usePathname();

  useDismiss(open, box, () => setOpen(false));

  const current = localeOf(pathname);

  return (
    <div className="lang" ref={box}>
      <button
        className={`${className} lang__btn`}
        type="button"
        aria-expanded={open}
        aria-controls="lang-panel"
        aria-label={label}
        onClick={() => setOpen((was) => !was)}
      >
        {/* Глобус, а не флаг: флаг обозначает страну, а не язык, и на нём
            всегда кто-то обижается. Кода языка рядом со значком нет —
            вторая строка под глобусом ломала ряд иконок; какой язык
            включён, видно в самом списке. */}
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <g fill="none" stroke="currentColor" strokeWidth="1.6">
            <circle cx="12" cy="12" r="8.4" />
            <ellipse cx="12" cy="12" rx="3.6" ry="8.4" />
            <path d="M3.9 9.3h16.2M3.9 14.7h16.2" strokeLinecap="round" />
          </g>
        </svg>
      </button>

      <div className="lang__panel" id="lang-panel" hidden={!open}>
        {LOCALES.map((locale) => (
          <Link
            key={locale}
            href={switchPath(pathname, locale)}
            hrefLang={locale}
            className={"lang__item" + (locale === current ? " is-active" : "")}
            aria-current={locale === current ? "true" : undefined}
            onClick={() => setOpen(false)}
          >
            <b>{TITLES[locale].short}</b>
            <span>{TITLES[locale].title}</span>
          </Link>
        ))}
      </div>
    </div>
  );
}
