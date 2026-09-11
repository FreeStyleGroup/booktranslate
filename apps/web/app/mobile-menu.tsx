"use client";

/* Меню шапки для узких экранов.

   Разделы страницы и обе кнопки на телефоне в полосу не помещаются:
   логотип, переключатель темы, «Войти» и «Регистрация» вместе требуют
   больше пятисот точек при трёхстах доступных, и полоса растягивала
   страницу — появлялась горизонтальная прокрутка на всех экранах сразу.
   Поэтому на узких экранах в полосе остаются логотип, тема и эта кнопка,
   а разделы и кнопки входа переезжают в раскрывающийся список.

   Заодно закрывается давняя дыра: навигация по разделам пряталась ниже
   1120 точек и на планшете не существовала вовсе — попасть в «Стоимость»
   можно было только прокруткой. */

import { useRef, useState } from "react";

import { useDismiss } from "./use-dismiss";

const SECTIONS = [
  { href: "#how", title: "Как работает" },
  { href: "#terms", title: "Терминология" },
  { href: "#who", title: "Кому" },
  { href: "#formats", title: "Форматы" },
  { href: "#price", title: "Стоимость" },
  { href: "#faq", title: "Вопросы" },
];

export function MobileMenu() {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useDismiss(open, box, () => setOpen(false));

  return (
    <div className="mmenu" ref={box}>
      <button
        className="top__theme mmenu__btn"
        type="button"
        aria-expanded={open}
        aria-controls="mmenu-panel"
        aria-label={open ? "Закрыть меню" : "Открыть меню"}
        onClick={() => setOpen((was) => !was)}
      >
        <svg viewBox="0 0 24 24" aria-hidden="true">
          {open ? (
            <path
              d="M6 6l12 12M18 6L6 18"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
            />
          ) : (
            <path
              d="M4 7h16M4 12h16M4 17h16"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
            />
          )}
        </svg>
      </button>

      {/* Панель рисуется всегда, а прячется стилями: иначе при открытии
          браузер заново считает раскладку и список прыгает. */}
      <div className="mmenu__panel" id="mmenu-panel" hidden={!open}>
        <nav className="mmenu__nav">
          {SECTIONS.map((section) => (
            <a key={section.href} href={section.href} onClick={() => setOpen(false)}>
              {section.title}
            </a>
          ))}
        </nav>

        <div className="mmenu__actions">
          <a className="btn btn--ghost btn--small" href="/login">
            Войти
          </a>
          <a className="btn btn--primary btn--small" href="/register">
            Регистрация <i aria-hidden="true">↗</i>
          </a>
        </div>
      </div>
    </div>
  );
}
