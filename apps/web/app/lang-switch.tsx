"use client";

/* Переключатель языка.

   Интерфейс пока только на русском, английский в работе. Кнопка стоит в
   шапке уже сейчас по двум причинам. Первая: место под неё — часть
   раскладки, и добавить её потом значит переверстать полосу заново, а на
   телефоне там счёт идёт на десяток точек. Вторая: посетитель из-за
   рубежа должен видеть, что о языке думали, даже если второй ещё не готов.

   🔥 Английский помечен как недоступный и не переключается. Кнопка,
   которая делает вид, что переключает, но оставляет русский текст, хуже
   отсутствующей: человек решает, что сайт сломан. */

import { useRef, useState } from "react";

import { useDismiss } from "./use-dismiss";

type Lang = {
  code: string;
  short: string;
  title: string;
  ready: boolean;
};

const LANGS: Lang[] = [
  { code: "ru", short: "RU", title: "Русский", ready: true },
  { code: "en", short: "EN", title: "English", ready: false },
];

export function LangSwitch({ className = "top__theme" }: { className?: string }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useDismiss(open, box, () => setOpen(false));

  const current = LANGS[0];

  return (
    <div className="lang" ref={box}>
      <button
        className={`${className} lang__btn`}
        type="button"
        aria-expanded={open}
        aria-controls="lang-panel"
        aria-label="Язык интерфейса"
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
        {LANGS.map((lang) => (
          <button
            key={lang.code}
            type="button"
            className={"lang__item" + (lang.code === current.code ? " is-active" : "")}
            disabled={!lang.ready}
            onClick={() => setOpen(false)}
          >
            <b>{lang.short}</b>
            <span>{lang.title}</span>
            {!lang.ready && <i>в работе</i>}
          </button>
        ))}
      </div>
    </div>
  );
}
