"use client";

/* Уведомления — стопкой в правом нижнем углу.

   Два вида. Успех — короткая фраза о сделанном, которое не видно на
   экране («файл проверен»); она исчезает сама через несколько секунд.
   Отказ — причина, по которой действие не сделано; он остаётся, пока его
   не закроют: причину надо успеть прочитать, а сообщение, исчезающее
   посреди чтения, хуже, чем никакого.

   Хост живёт в корневой раскладке, а состояние — в контексте: иначе
   каждая страница держала бы свою стопку, и уведомления соседних экранов
   накладывались бы друг на друга.

   Одно исключение — окно подтверждения: модальное окно браузер рисует
   поверх всей страницы, и уведомление оказалось бы под его затемнением.
   Там отказ остаётся внутри окна (`confirm-dialog.tsx`). */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import "./toast.css";

// Сколько держать сообщение об успехе. Четыре секунды — успеть прочитать
// короткую фразу, не успеть забыть, к чему она относилась.
const SHOWN_MS = 4000;

// Больше трёх уведомлений разом не читают: старые уходят, уступая место.
const MAX_SHOWN = 3;

type Kind = "ok" | "error";

type Notice = { id: number; kind: Kind; text: string };

export type Toast = {
  /** Короткая фраза о сделанном. Исчезает сама. */
  ok: (text: string) => void;
  /** Причина отказа. Остаётся, пока не закроют. */
  error: (text: string) => void;
};

const Context = createContext<Toast | null>(null);

export function ToastHost({ children }: { children: ReactNode }) {
  const [notices, setNotices] = useState<Notice[]>([]);
  const next = useRef(0);

  const dismiss = useCallback((id: number) => {
    setNotices((shown) => shown.filter((notice) => notice.id !== id));
  }, []);

  const push = useCallback((kind: Kind, text: string) => {
    next.current += 1;
    const id = next.current;

    setNotices((shown) => [...shown, { id, kind, text }].slice(-MAX_SHOWN));
  }, []);

  const toast = useMemo<Toast>(
    () => ({ ok: (text) => push("ok", text), error: (text) => push("error", text) }),
    [push],
  );

  return (
    <Context.Provider value={toast}>
      {children}

      {/* Две области объявлений, и обе есть всегда, пустые в том числе:
          появившуюся вместе с текстом программа чтения с экрана не
          произнесёт. Отказ объявляется сразу, успех — в паузе. */}
      <div className="ui-toasts">
        <div role="alert" aria-live="assertive" className="ui-toasts__lane">
          {notices
            .filter((notice) => notice.kind === "error")
            .map((notice) => (
              <Card key={notice.id} notice={notice} onDismiss={dismiss} />
            ))}
        </div>
        <div role="status" aria-live="polite" className="ui-toasts__lane">
          {notices
            .filter((notice) => notice.kind === "ok")
            .map((notice) => (
              <Card key={notice.id} notice={notice} onDismiss={dismiss} />
            ))}
        </div>
      </div>
    </Context.Provider>
  );
}

function Card({ notice, onDismiss }: { notice: Notice; onDismiss: (id: number) => void }) {
  // Действие закрытия — стабильное: на каждую перерисовку стопки новая
  // функция перезапускала бы отсчёт показа с нуля.
  const onClose = useCallback(() => onDismiss(notice.id), [onDismiss, notice.id]);

  // Время показа отсчитывается от появления карточки, а не от вызова:
  // уведомление часто создаётся вместе с обновлением страницы, и если то
  // идёт дольше нескольких секунд, отсчёт от вызова убрал бы карточку
  // раньше, чем её успели увидеть. Отказ не исчезает сам вовсе.
  useEffect(() => {
    if (notice.kind !== "ok") {
      return;
    }

    const timer = setTimeout(onClose, SHOWN_MS);

    return () => clearTimeout(timer);
  }, [notice.kind, onClose]);

  return (
    <div className={notice.kind === "error" ? "ui-toast is-error" : "ui-toast"}>
      <span className="ui-toast__mark" aria-hidden="true">
        {notice.kind === "error" ? "!" : "✓"}
      </span>
      <p className="ui-toast__text">{notice.text}</p>
      <button className="ui-toast__close" type="button" aria-label="Закрыть" onClick={onClose}>
        ×
      </button>
    </div>
  );
}

/** Уведомления — вне хоста пустое действие, а не падение: показать
 *  сообщение — не повод ронять экран, который работает. */
export function useToast(): Toast {
  const toast = useContext(Context);

  return useMemo(() => toast ?? { ok: () => undefined, error: () => undefined }, [toast]);
}

/** Показать отказ уведомлением, когда он появится.
 *
 * Форма объявляет, что ошибка есть, а как её показать — решает хост.
 * `at` — признак нового ответа: два одинаковых отказа подряд на два
 * нажатия — два события, и показать надо оба. У результата серверного
 * действия это сам объект результата: на каждый ответ он новый.
 */
export function ReportError({
  error,
  at,
}: {
  error: string | null | undefined;
  at?: unknown;
}) {
  const toast = useToast();

  useEffect(() => {
    if (error !== null && error !== undefined && error !== "") {
      toast.error(error);
    }
  }, [error, at, toast]);

  return null;
}
