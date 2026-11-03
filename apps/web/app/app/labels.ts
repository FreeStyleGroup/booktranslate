import type {
  EditReason,
  IssueCategory,
  IssueEventKind,
  IssueSeverity,
  IssueStatus,
  RegressionDecision,
  RegressionKind,
  ReviewKind,
  ReviewRun,
} from "../lib/work";

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

/** Роль блока в книге: по раскладу видно, что за файл принесли.
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
export const REVISION_ORIGIN_LABEL: Record<string, string> = {
  model: "модель",
  memory: "готовый перевод",
  human: "человек",
  copy: "без перевода",
};

export const REVISION_ORIGIN_CHIP: Record<string, string> = {
  model: "chip chip--info",
  memory: "chip chip--info",
  human: "chip chip--ok",
  copy: "chip chip--info",
};

export const REVISION_STAGE_LABEL: Record<string, string> = {
  draft: "черновик",
  working: "рабочая",
  final_candidate: "кандидат в выпуск",
};

export const QA_CHECK_LABEL: Record<string, string> = {
  empty: "Пустой перевод",
  untranslated: "Не переведено",
  numbers: "Числа",
  signs: "Знак числа",
  ranges: "Диапазон",
  units: "Единицы",
  variables: "Имена из кода",
  cross_references: "Ссылки",
  object_placeholders: "Защищённые объекты",
  placeholders: "Подстановки и разметка",
  list_numbering: "Нумерация списка",
  glossary: "Термины",
  first_use: "Первое употребление",
  code_changed: "Листинг",
  semantic: "Смысловая сверка",
};

export const QA_RULE_LABEL: Record<string, string> = {
  optional_term: "термин необязательный",
  localized_marker: "буква пункта заменена на русскую",
};

export const REGRESSION_KIND_LABEL: Record<RegressionKind, string> = {
  same_source_repeat: "тот же исходный текст",
  term_usage: "тот же термин",
  object_reference: "упоминание объекта",
  cross_reference: "ссылка на раздел",
  adjacent_context: "соседний блок",
  table_caption: "подпись таблицы",
  figure_caption: "рисунок",
};

export const REGRESSION_DECISION_LABEL: Record<RegressionDecision, string> = {
  pending: "ждёт решения",
  not_affected: "не затронуто",
  propagated: "исправление применено",
  issue_created: "заведено замечание",
};

export const ISSUE_CATEGORY_LABEL: Record<IssueCategory, string> = {
  translation: "Перевод",
  terminology: "Терминология",
  semantic: "Смысл",
  number: "Числа",
  formula: "Формула",
  table: "Таблица",
  figure: "Рисунок",
  code: "Код",
  technical: "Техническая",
  style: "Стиль",
  cross_reference: "Перекрёстная ссылка",
  source_error: "Ошибка оригинала",
  layout: "Вёрстка",
};

export const ISSUE_CATEGORY_ORDER = Object.keys(ISSUE_CATEGORY_LABEL) as IssueCategory[];

export const ISSUE_SEVERITY_LABEL: Record<IssueSeverity, string> = {
  critical: "Критичная",
  major: "Серьёзная",
  minor: "Незначительная",
};

export const ISSUE_SEVERITY_ORDER = Object.keys(ISSUE_SEVERITY_LABEL) as IssueSeverity[];

export const ISSUE_SEVERITY_CHIP: Record<IssueSeverity, string> = {
  critical: "chip chip--danger",
  major: "chip chip--warn",
  minor: "chip chip--info",
};

// Критерии те же, что в docs/DECISIONS.md: оценивающий должен видеть их в момент выбора.
export const ISSUE_SEVERITY_HINT: Record<IssueSeverity, string> = {
  critical: "Читатель сделает неверно: число, формула, код, потерянный или обратный смысл.",
  major: "Смысл или термин искажён, но опасности нет: читатель заметит или переспросит.",
  minor: "Стиль и оформление: на понимание не влияет.",
};

export const ISSUE_STATUS_LABEL: Record<IssueStatus, string> = {
  new: "Новая",
  needs_clarification: "Нужно уточнение",
  confirmed: "Подтверждена",
  fixed: "Исправлена",
  verified: "Проверена",
  closed: "Закрыта",
  rejected: "Отклонена",
  reopened: "Открыта заново",
};

export const ISSUE_STATUS_ORDER = Object.keys(ISSUE_STATUS_LABEL) as IssueStatus[];

export const ISSUE_STATUS_CHIP: Record<IssueStatus, string> = {
  new: "chip chip--warn",
  needs_clarification: "chip chip--warn",
  confirmed: "chip chip--danger",
  fixed: "chip chip--info",
  verified: "chip chip--info",
  closed: "chip chip--ok",
  rejected: "chip",
  reopened: "chip chip--warn",
};

export const ISSUE_EVENT_LABEL: Record<IssueEventKind, string> = {
  created: "Зарегистрирована",
  status_changed: "Состояние изменено",
  reclassified: "Изменена классификация",
  assigned: "Изменено назначение",
  commented: "Комментарий",
  attached: "Приложен файл",
  archived: "Убрана в архив",
  restored: "Возвращена из архива",
};

export const REVISION_ORIGIN_COLOR: Record<string, string> = {
  model: "#4f6ef7",
  memory: "#2bb673",
  human: "#f0a63a",
  copy: "#94a3b8",
};

export const JOB_LABEL: Record<string, string> = {
  waiting: "в очереди",
  running: "переводится",
  done: "готово",
  failed: "сорвалось",
  cancelled: "остановлено",
};

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
  proposed: "уходит модели подсказкой, блок не помечает",
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

// Названия языков заданы словарём, а не `Intl`: сервер и браузер должны показать одно и то же.
const LANGUAGE_NAME: Record<string, string> = {
  ru: "русский",
  en: "английский",
  de: "немецкий",
  fr: "французский",
  es: "испанский",
  it: "итальянский",
  pt: "португальский",
  zh: "китайский",
  ja: "японский",
  ko: "корейский",
  ar: "арабский",
  tr: "турецкий",
  pl: "польский",
  uk: "украинский",
  nl: "нидерландский",
  cs: "чешский",
  sv: "шведский",
  fi: "финский",
  he: "иврит",
  hi: "хинди",
};

export function languageName(code: string): string {
  return LANGUAGE_NAME[code.split("-")[0].toLowerCase()] ?? code;
}

/** Языковая пара словами: «английский → русский». */
export function languagePair(source: string, target: string): string {
  return `${languageName(source)} → ${languageName(target)}`;
}

export const REVIEW_KIND_LABEL: Record<ReviewKind, string> = {
  technical: "Техническая редактура",
  literary: "Литературная редактура",
  final_compare: "Финальная сверка",
};

export const EDIT_REASON_LABEL: Record<EditReason, string> = {
  style: "Стиль",
  calque: "Калька",
  readability: "Читаемость",
};

export const EDIT_REASON_HINT: Record<EditReason, string> = {
  style: "Текст верен, но звучит неудачно.",
  calque: "Конструкция повторяет исходный язык.",
  readability: "Фраза тяжёлая: её трудно прочитать с первого раза.",
};

export const EDIT_REASON_ORDER = Object.keys(EDIT_REASON_LABEL) as EditReason[];

/** Сколько посмотрено: вниз, чтобы 99,9% не показывались как 100. */
export function reviewPercent(run: ReviewRun): number {
  const total = run.blocks_total + run.objects_total;

  if (total === 0) {
    return 0;
  }

  return Math.floor(((run.blocks_done + run.objects_done) * 100) / total);
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
