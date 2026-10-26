"use client";

/* Кнопка «скопировать код».

   Коды — рабочая валюта этого сервиса: по `BK01-CH03-ERR-0001` замечание
   ищут в реестре, называют в переписке и ставят в задачу. Набирать такой
   код руками — значит однажды перепутать в нём цифру и обсуждать не то
   замечание.

   Буфер обмена бывает недоступен: без защищённого соединения
   `navigator.clipboard` отсутствует, а в браузере с запретом на запись
   вызов отклоняется. Тогда кнопка показывает значение целиком и просит
   скопировать его руками — и остаётся в этом виде, пока на неё не нажмут
   снова: отметка, исчезающая через секунду, не годится для того, что
   человеку надо успеть выделить. */

import { useRef, useState } from "react";

type State = "idle" | "copied" | "failed";

// Сколько держать отметку «скопировано». Короче — не успеешь заметить,
// дольше — отметка переживёт то действие, к которому относилась.
const SHOWN_MS = 1600;

export function CopyId({
  value,
  title,
  label,
}: {
  /** Что попадёт в буфер обмена — всегда целиком. */
  value: string;
  /** Чем это является: уходит в подпись действия для чтения с экрана. */
  title?: string;
  /** Чем заменить значение на экране. Для контрольной суммы: все 64 знака
   *  в строку не встанут, а сверяют их глазом не целиком. */
  label?: string;
}) {
  const [state, setState] = useState<State>("idle");
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);

  async function copy(): Promise<void> {
    clearTimeout(timer.current);

    try {
      await navigator.clipboard.writeText(value);
      setState("copied");
      timer.current = setTimeout(() => setState("idle"), SHOWN_MS);
    } catch {
      // Ни запрета, ни отсутствия буфера нам не исправить — остаётся
      // показать значение целиком, чтобы его можно было выделить мышью.
      setState("failed");
    }
  }

  const failed = state === "failed";

  return (
    <button
      className={failed ? "ui-code is-failed" : "ui-code"}
      type="button"
      // Подпись к действию, а не к значению: «BK01» кнопкой не звучит.
      aria-label={`Скопировать ${title ?? "код"} ${value}`}
      onClick={() => {
        void copy();
      }}
    >
      {/* В отказе — значение целиком, даже если на экране стояла краткая
          запись: копировать его человек будет глазами и мышью. */}
      <span>{failed ? value : (label ?? value)}</span>

      <span className="ui-code__mark" aria-hidden="true">
        {state === "copied" ? "✓" : failed ? "✎" : "⧉"}
      </span>

      {/* Исход словами и для чтения с экрана: значок галочки программа
          чтения не произносит. */}
      <span className="ui-code__said" role="status">
        {state === "copied" ? "Код скопирован" : failed ? "Скопируйте код вручную" : ""}
      </span>
    </button>
  );
}
