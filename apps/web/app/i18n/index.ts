/* Словарь витрины: выбор языка и подстановка значений.
 *
 * Отдельным файлом от самих словарей, чтобы страница импортировала одну
 * функцию, а не оба языка по именам: так забыть подключить английский
 * невозможно — он подключён здесь один раз.
 */

import type { Metadata } from "next";

import { localePath, type Locale } from "./config";
import { en } from "./en";
import { ru, type Dictionary } from "./ru";

export type { Dictionary };

export function dictionary(locale: Locale): Dictionary {
  return locale === "en" ? en : ru;
}

/** Канонический адрес страницы и её двойник на другом языке.
 *
 * `hreflang` — единственное, по чему поисковик понимает, что две страницы
 * это один документ на разных языках. Без него он считает их разными
 * страницами с похожим содержимым и показывает одну из двух на свой
 * выбор — обычно не ту. Атрибут `lang` у разметки на это не влияет вовсе.
 *
 * `x-default` — куда вести того, чей язык не подошёл ни к одному: русская
 * версия, она же основная.
 */
export function alternates(locale: Locale, path: string): Metadata["alternates"] {
  return {
    canonical: localePath(locale, path),
    languages: {
      ru: localePath("ru", path),
      en: localePath("en", path),
      "x-default": localePath("ru", path),
    },
  };
}

export { fill } from "./config";
