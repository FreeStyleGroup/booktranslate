"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

/* Появление блока при подходе к нему.

   Наблюдатель, а не обработчик прокрутки: обработчик срабатывает сотни раз
   в секунду и дёргает раскладку, наблюдатель — ровно один раз на блок.
   После показа он отключается: анимация «туда-обратно» при листании вверх
   раздражает и мешает перечитывать.

   Без JavaScript блоки остаются видимыми — правило в <noscript> у разметки
   страницы. Прячет содержимое только тот, кто способен его показать. */
export function Reveal({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [shown, setShown] = useState(false);

  useEffect(() => {
    const node = ref.current;

    if (node === null) {
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setShown(true);
            observer.disconnect();
          }
        }
      },
      // Блок считается показанным, когда действительно вошёл в экран, а не
      // коснулся его нижней кромки: иначе анимация проходит за пределами
      // видимости и человек видит уже готовое.
      { rootMargin: "0px 0px -12% 0px", threshold: 0.05 },
    );

    observer.observe(node);

    return () => observer.disconnect();
  }, []);

  const classes = ["reveal", shown ? "is-visible" : "", className ?? ""]
    .filter(Boolean)
    .join(" ");

  return (
    <div ref={ref} className={classes}>
      {children}
    </div>
  );
}
