"use client";

/* Подтверждение необратимого действия.

   Своя модалка, а не системный `confirm()`: тот показывает голый текст
   шрифтом браузера, не даёт выделить главное и закрывается любой из двух
   одинаковых кнопок. Здесь опасное действие подписано словами и окрашено,
   отмена — рядом, а отказ API остаётся в окне, а не пропадает вместе с
   ним.

   Под капотом — `<dialog>`: он сам держит фокус внутри, закрывается по
   Escape и затемняет всё остальное. Открытие и закрытие идут за
   состоянием снаружи — эффект только доводит DOM до него. */

import { useEffect, useRef, type ReactNode } from "react";

export function ConfirmDialog({
  open,
  title,
  children,
  confirmLabel,
  busyLabel,
  busy,
  error,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  children: ReactNode;
  confirmLabel: string;
  busyLabel: string;
  busy: boolean;
  error: string | null;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;

    if (dialog === null) {
      return;
    }

    if (open && !dialog.open) {
      dialog.showModal();
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open]);

  return (
    <dialog
      ref={ref}
      className="wk-dialog"
      aria-labelledby="wk-dialog-title"
      onCancel={(event) => {
        // Escape: закрыть через состояние, а не мимо него.
        event.preventDefault();
        if (!busy) {
          onCancel();
        }
      }}
      onClick={(event) => {
        // Нажатие по затемнению — сам элемент диалога, а не его содержимое.
        if (event.target === event.currentTarget && !busy) {
          onCancel();
        }
      }}
    >
      <div className="wk-dialog__body">
        <h3 id="wk-dialog-title">{title}</h3>
        <div className="wk-dialog__text">{children}</div>

        {error !== null && (
          <p className="form__error" role="alert">
            {error}
          </p>
        )}

        <div className="wk-actions">
          <button className="btn btn--danger" type="button" disabled={busy} onClick={onConfirm}>
            {busy ? busyLabel : confirmLabel}
          </button>
          <button className="btn btn--ghost" type="button" disabled={busy} onClick={onCancel}>
            Отмена
          </button>
        </div>
      </div>
    </dialog>
  );
}
