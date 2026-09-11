"use client";

/* Кнопка бокового меню для узких экранов.

   На телефоне сетка кабинета складывается в одну колонку, и меню из
   тринадцати разделов оказывалось над содержимым: чтобы добраться до
   самого кабинета, приходилось пролистать весь список. Поэтому на узких
   экранах меню становится выдвижной панелью, а открывает её эта кнопка.

   Состояние держится классом на <body>, а не в React-дереве: боковая
   панель отрисована в серверной раскладке выше по дереву, и поднимать
   ради одного переключателя всю раскладку в клиентскую — цена больше
   пользы. */

import { useEffect, useState } from "react";

const OPEN_CLASS = "nav-open";

export function NavToggle() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    document.body.classList.toggle(OPEN_CLASS, open);

    return () => {
      document.body.classList.remove(OPEN_CLASS);
    };
  }, [open]);

  useEffect(() => {
    if (!open) {
      return;
    }

    function onKey(event: KeyboardEvent): void {
      if (event.key === "Escape") {
        setOpen(false);
      }
    }

    /* Закрытие по нажатию на затемнение и по переходу в раздел: ссылки
       живут в серверной разметке, обработчик на каждую не повесить —
       ловим всплывающее событие от всей панели. */
    function onPointer(event: MouseEvent): void {
      const target = event.target as HTMLElement;
      if (target.closest(".cab__side a") || target.closest(".cab__scrim")) {
        setOpen(false);
      }
    }

    document.addEventListener("keydown", onKey);
    document.addEventListener("click", onPointer);

    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("click", onPointer);
    };
  }, [open]);

  return (
    <>
      <button
        className="cab__icon cab__burger"
        type="button"
        aria-expanded={open}
        aria-label={open ? "Закрыть меню" : "Открыть меню"}
        onClick={() => setOpen((was) => !was)}
      >
        <svg viewBox="0 0 24 24" aria-hidden="true" width="18" height="18">
          <path
            d={open ? "M6 6l12 12M18 6L6 18" : "M4 7h16M4 12h16M4 17h16"}
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
          />
        </svg>
      </button>

      {open && <div className="cab__scrim" aria-hidden="true" />}
    </>
  );
}
