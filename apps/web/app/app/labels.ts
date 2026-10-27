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

/** Где книга в конвейере. */
export const BOOK_STATUS_LABEL: Record<string, string> = {
  draft: "Черновик",
  in_progress: "В работе",
  released: "Выпущена",
};

export const BOOK_STATUS_CHIP: Record<string, string> = {
  draft: "chip chip--info",
  in_progress: "chip chip--warn",
  released: "chip chip--ok",
};

/** Зачем файл в комплекте книги. */
export const SOURCE_ROLE_LABEL: Record<string, string> = {
  primary_text: "Основной текст",
  visual_reference: "Визуальный эталон",
  auxiliary: "Вспомогательный",
  code_source: "Исходники кода",
};

/** Чем роли отличаются. Показывается там, где роль выбирают: без
 *  пояснения «визуальный эталон» и «вспомогательный» выглядят одинаково. */
export const SOURCE_ROLE_HINT: Record<string, string> = {
  primary_text: "из него берут текст — такой файл у книги один",
  visual_reference: "по нему сверяют вёрстку, текст из него не берут",
  auxiliary: "приложения, глоссарии заказчика, письма",
  code_source: "листинги в исходном виде — переносятся побайтно",
};

export const SOURCE_ROLE_CHIP: Record<string, string> = {
  primary_text: "chip chip--ok",
  visual_reference: "chip chip--info",
  auxiliary: "chip chip--info",
  code_source: "chip chip--info",
};

/** Состояние границ главы. */
export const BOUNDARY_LABEL: Record<string, string> = {
  draft: "Черновик",
  approved: "Утверждена",
};

export const BOUNDARY_CHIP: Record<string, string> = {
  draft: "chip chip--warn",
  approved: "chip chip--ok",
};

/** Откуда взялись границы — чтобы предложенное и выставленное руками
 *  проверяли по-разному. */
export const ORIGIN_LABEL: Record<string, string> = {
  heading: "по заголовкам",
  path: "по файлам EPUB",
  page: "по страницам PDF",
  whole: "документ целиком",
  manual: "вручную",
};

/** Где в исходнике начинается глава или раздел — так, как это найдёт
 *  человек: файл EPUB, страница PDF, строка Markdown. */
export function whereIs(locator: Record<string, string | number>): string | null {
  if (typeof locator.page === "number") {
    return `стр. ${locator.page}`;
  }

  if (typeof locator.href === "string") {
    // Путь внутри архива человеку не нужен — нужно имя файла.
    return locator.href.split("/").pop() ?? locator.href;
  }

  if (typeof locator.line === "number") {
    return `строка ${locator.line}`;
  }

  return null;
}

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

/** Специальный объект главы — одним словом, как его называют в книге. */
export const OBJECT_ONE: Record<string, string> = {
  figure: "Рисунок",
  table: "Таблица",
  equation: "Формула",
  code: "Листинг",
};

/** Вкладки объектов главы. Порядок — порядок вкладок. */
export const OBJECT_TABS: { type: string; title: string; empty: string }[] = [
  { type: "figure", title: "Рисунки", empty: "Рисунков в этой версии мастера нет." },
  { type: "table", title: "Таблицы", empty: "Таблиц в этой версии мастера нет." },
  { type: "equation", title: "Формулы", empty: "Выносных формул в этой версии мастера нет." },
  { type: "code", title: "Код", empty: "Листингов в этой версии мастера нет." },
];

/** Как блок упоминает объект: ссылкой автора или номером в тексте. */
export const MENTION_LABEL: Record<string, string> = {
  link: "ссылка",
  label: "по номеру",
};

/** Разряд записи словаря: что это за слово, а не «договорились ли мы». */
export const GLOSSARY_KIND: Record<string, string> = {
  term: "Термин",
  abbreviation: "Аббревиатура",
  do_not_translate: "Не переводится",
  notation: "Обозначение",
  proper_name: "Имя собственное",
};

/** Чем разряды отличаются. Показывается там, где разряд выбирают: без
 *  пояснения «обозначение» и «не переводится» выглядят одинаково. */
export const GLOSSARY_KIND_HINT: Record<string, string> = {
  term: "обычное слово: thread → поток",
  abbreviation: "TLS, SDK — при первом употреблении раскрывается",
  do_not_translate: "JSON, HTTP, имя поля — переносится дословно",
  notation: "O(n), Δt, x₀ — переводу не подлежит, но различается",
  proper_name: "фирма, продукт, стандарт — решает человек",
};

/** Состояние решения по термину: договорились ли, а не что это. */
export const GLOSSARY_STATUS: Record<string, string> = {
  proposed: "Предложен",
  confirmed: "Подтверждён",
  needs_review: "Перепроверить",
  needs_unification: "Унифицировать",
  retired: "Снят",
};

export const GLOSSARY_STATUS_HINT: Record<string, string> = {
  proposed: "уходит модели подсказкой, сегмент не помечает",
  confirmed: "применяется как требование — и проверяется",
  needs_review: "решение под вопросом, подсказкой пока идёт",
  needs_unification: "в разных главах названо по-разному",
  retired: "дубликат или ошибка — в работу не идёт",
};

/** Что сделать с термином при первом употреблении в книге. */
export const FIRST_USE_RULE: Record<string, string> = {
  none: "Ничего особого",
  expand: "Раскрыть сокращение",
  original: "Дать оригинал в скобках",
};

export const FIRST_USE_HINT: Record<string, string> = {
  none: "термин просто употребляется",
  expand: "программируемый логический контроллер (ПЛК), дальше — ПЛК",
  original: "предохранительный клапан (relief valve), дальше — без скобок",
};

/** Состояние версии глоссария. */
export const VERSION_STATUS_LABEL: Record<string, string> = {
  draft: "Черновик",
  approved: "Утверждена",
  superseded: "Заменена",
};

export const VERSION_STATUS_CHIP: Record<string, string> = {
  draft: "chip chip--warn",
  approved: "chip chip--ok",
  superseded: "chip chip--info",
};

/** Чем обязательный термин версии отличается от предыдущей. */
export const TERM_CHANGE_LABEL: Record<string, string> = {
  added: "Появился",
  changed: "Изменён",
  removed: "Снят",
};

export const TERM_CHANGE_CHIP: Record<string, string> = {
  added: "chip chip--ok",
  changed: "chip chip--warn",
  removed: "chip chip--danger",
};

/** Откуда запись словаря. Загрузка называется по источнику из файла. */
export function glossarySource(source: string): string {
  if (source === "manual") {
    return "вручную";
  }

  if (source === "extracted") {
    return "из книги";
  }

  if (source === "platform") {
    return "из общего словаря";
  }

  return source.startsWith("import:") ? `загрузка: ${source.slice(7)}` : source;
}

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

/** Роль в рабочем пространстве. */
export const ROLE_LABEL: Record<string, string> = {
  owner: "Владелец",
  admin: "Администратор",
  manager: "Менеджер",
  translator: "Переводчик",
  reviewer: "Редактор",
  viewer: "Наблюдатель",
};

/** Что роль разрешает — там, где роль выбирают: без пояснения «менеджер»
 *  и «администратор» выглядят одинаково. Списано с проверок прав в API. */
export const ROLE_HINT: Record<string, string> = {
  owner: "всё, включая назначение владельцев",
  admin: "команда, настройки и вся работа с книгами",
  manager: "проекты, книги, термины, перевод и приёмка",
  translator: "загрузка и перевод книг, словарь, правка",
  reviewer: "правка и приёмка перевода, выгрузка",
  viewer: "только просмотр и выгрузка",
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

/** Контрольная сумма для глаза: первые и последние знаки.
 *
 * Полные 64 знака в таблицу не встанут, а сверяют их не целиком: человек
 * смотрит, тот ли это файл, что присылали, — для этого хватает краёв.
 */
export function shortHash(hash: string | null): string {
  if (hash === null) {
    return "—";
  }

  return hash.length <= 16 ? hash : `${hash.slice(0, 8)}…${hash.slice(-4)}`;
}
