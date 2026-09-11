/* Подписи к состояниям, которые приходят с API.

   Ключи API отдаёт как есть — переводить их там значило бы вшить язык
   интерфейса в данные. Подписи же собраны в одном месте намеренно: одно и
   то же состояние показывают обзор, список документов и карточка, и три
   набора слов для одного состояния — это интерфейс, в котором «на вычитке»
   и «ждёт редактора» выглядят как разные вещи. */

export const DOCUMENT_LABEL: Record<string, string> = {
  uploaded: "Загружен",
  parsing: "Разбирается",
  parsed: "Разобран",
  translating: "Переводится",
  review: "На вычитке",
  done: "Готов",
  failed: "Ошибка",
};

/** Каким значком помечать состояние документа в списке. */
export const DOCUMENT_CHIP: Record<string, string> = {
  uploaded: "chip chip--info",
  parsing: "chip chip--info",
  parsed: "chip chip--ok",
  translating: "chip chip--info",
  review: "chip chip--warn",
  done: "chip chip--ok",
  failed: "chip chip--danger",
};

export const SEGMENT_LABEL: Record<string, string> = {
  new: "Не переведено",
  machine: "Перевод модели",
  memory: "Из памяти",
  flagged: "С замечаниями",
  edited: "Правка человека",
  approved: "Принято",
};

export const SEGMENT_COLOR: Record<string, string> = {
  approved: "#2f6bff",
  edited: "#12b981",
  memory: "#0ea5a5",
  machine: "#8b5cf6",
  flagged: "#f0a63a",
  new: "#94a3b8",
};

/** Роль сегмента в книге: по раскладу видно, что за файл принесли.
 *
 * Два набора, потому что подписи стоят в разных местах: в разбивке речь
 * о множестве («Абзацы — 10»), а в списке — об одной строке, и «Абзацы»
 * над единственным абзацем читается как ошибка.
 */
export const KIND_LABEL: Record<string, string> = {
  paragraph: "Абзацы",
  heading: "Заголовки",
  list_item: "Пункты списков",
  table_cell: "Ячейки таблиц",
  caption: "Подписи",
  warning: "Предупреждения",
  code: "Код и формулы",
};

export const KIND_ONE: Record<string, string> = {
  paragraph: "Абзац",
  heading: "Заголовок",
  list_item: "Пункт списка",
  table_cell: "Ячейка таблицы",
  caption: "Подпись",
  warning: "Предупреждение",
  code: "Код",
};

export const CHECK_LABEL: Record<string, string> = {
  numbers: "Числа",
  placeholders: "Подстановки",
  glossary: "Термин",
  first_use: "Раскрытие",
  untranslated: "Не переведено",
  empty: "Пусто",
};

export const CHECK_CHIP: Record<string, string> = {
  numbers: "chip chip--danger",
  placeholders: "chip chip--danger",
  glossary: "chip chip--warn",
  first_use: "chip chip--info",
  untranslated: "chip chip--warn",
  empty: "chip chip--danger",
};

/** Формат исходника — так, как его называет человек, а не разборщик. */
export const FORMAT_LABEL: Record<string, string> = {
  pdf: "PDF",
  docx: "DOCX",
  html: "HTML",
  markdown: "Markdown",
  xliff: "XLIFF",
  epub: "EPUB",
  txt: "Текст",
};

export function thousands(value: number): string {
  return value.toLocaleString("ru-RU");
}

/** Слово в числе: 1 книга, 2 книги, 5 книг.
 *
 * Без этого подписи приходится строить так, чтобы число стояло отдельно
 * от слова («книг: 5»), а это первый признак интерфейса, который писали
 * на английском и перевели.
 */
export function plural(amount: number, one: string, few: string, many: string): string {
  const last = amount % 10;
  const teen = amount % 100 >= 11 && amount % 100 <= 14;

  if (teen || last === 0 || last >= 5) {
    return many;
  }

  return last === 1 ? one : few;
}

/** Размер файла словами, а не в байтах: байты человек не читает. */
export function fileSize(bytes: number | null): string {
  if (bytes === null) {
    return "—";
  }

  if (bytes < 1024) {
    return `${bytes} Б`;
  }

  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(0)} КБ`;
  }

  return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`;
}

/** Сколько это страниц. Считается по 1800 знаков — учётная страница,
 *  по которой в переводе меряют объём и назначают цену. */
export function pages(characters: number): number {
  return Math.max(1, Math.round(characters / 1800));
}

export function when(iso: string): string {
  return new Date(iso).toLocaleString("ru-RU", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}
