"use client";

/* Короткие сообщения о том, что действие прошло.

   Нужны там, где результат не виден на экране. «Роль изменена» видно по
   строке таблицы, и говорить об этом словами незачем; а вот «проверка
   запущена» или «код скопирован» не меняют ничего видимого — без
   сообщения человек нажимает второй раз.

   Об отказах тост не сообщает. Отказ остаётся у того действия, которое
   его вызвало: сообщение, которое само исчезает через четыре секунды, —
   плохое место для причины, по которой работа не сделана.

   Живёт в раскладке кабинета, а состояние — в контексте: иначе каждая
   страница держала бы своё и сообщения со соседних экранов накладывались
   бы друг на друга. */

import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";

// Сколько держать сообщение. Четыре секунды — успеть прочитать короткую
// фразу, не успеть забыть, к чему она относилась.
const SHOWN_MS = 4000;

type Said = { id: number; text: string };

const Context = createContext<((text: string) => void) | null>(null);

export function ToastHost({ children }: { children: ReactNode }) {
  const [said, setSaid] = useState<Said | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  // Ключ сообщения, а не его текст: два одинаковых сообщения подряд —
  // это два события, и область чтения с экрана обязана произнести оба.
  const next = useRef(0);

  const say = useCallback((text: string) => {
    next.current += 1;
    setSaid({ id: next.current, text });

    clearTimeout(timer.current);
    timer.current = setTimeout(() => setSaid(null), SHOWN_MS);
  }, []);

  return (
    <Context.Provider value={say}>
      {children}

      {/* Область объявлений есть всегда, пустая в том числе: добавленная
          вместе с текстом, она не прочитается — программа чтения следит
          за изменениями внутри области, а не за её появлением. */}
      <div className="ui-toasts" role="status" aria-live="polite">
        {said !== null && (
          <p className="ui-toast" key={said.id}>
            {said.text}
          </p>
        )}
      </div>
    </Context.Provider>
  );
}

/** Сказать короткую фразу о сделанном.
 *
 * Вне раскладки кабинета возвращает пустое действие, а не падает: тост —
 * это сообщение об успехе, и ронять из-за него экран, который работает,
 * нельзя.
 */
export function useToast(): (text: string) => void {
  const say = useContext(Context);

  return useCallback(
    (text: string) => {
      say?.(text);
    },
    [say],
  );
}
