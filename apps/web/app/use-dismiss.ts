"use client";

import { useEffect, type RefObject } from "react";

/** Закрыть всплывающий блок по Esc и по нажатию мимо него.
 *
 * Отдельным хуком, а не копией в каждом меню: закрываться они обязаны
 * одинаково, а разъезжаются такие вещи незаметно — в одном меню Esc
 * работает, в другом нет, и найдётся это только у пользователя.
 */
export function useDismiss(
  open: boolean,
  box: RefObject<HTMLElement | null>,
  close: () => void,
): void {
  useEffect(() => {
    if (!open) {
      return;
    }

    function onKey(event: KeyboardEvent): void {
      if (event.key === "Escape") {
        close();
      }
    }

    function onPointer(event: MouseEvent): void {
      if (box.current && !box.current.contains(event.target as Node)) {
        close();
      }
    }

    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointer);

    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointer);
    };
  }, [open, box, close]);
}
