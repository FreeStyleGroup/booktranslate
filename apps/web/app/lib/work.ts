/* Данные работы: проекты, документы, сегменты.

   Типы описаны здесь, а не рядом с каждой страницей: один и тот же
   документ показывают список, карточка и обзор, и три описания одного
   ответа разъедутся на первой же правке API.

   Загрузка тоже общая. Каждая страница кабинета делает одно и то же:
   берёт токен, спрашивает API, а на отказ по токену уходит на продление
   сеанса. Повторённое на пяти страницах, это правило однажды будет
   забыто на шестой — и та покажет пустой экран вошедшему человеку. */

import { redirect } from "next/navigation";

import { apiFetch, unauthorized } from "./api";
import { accessToken, organizationId, renewUrl } from "./session";

export type Project = {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  source_language: string;
  target_language: string;
  created_at: string;
  updated_at: string;
};

/** Что книга переводится, что уже вышла. */
export type BookStatus = "draft" | "in_progress" | "released";

/** Издание книги.
 *
 * Код выдаёт сервер и больше не меняет: он входит в номера замечаний
 * (`BK01-CH03-ERR-0001`), и переделать его потом — значит потерять
 * прослеживаемость всего, что на него ссылается.
 */
export type Book = {
  id: string;
  project_id: string;
  code: string;
  title: string;
  author: string | null;
  edition_label: string | null;
  source_language: string;
  target_language: string;
  status: BookStatus;
  created_at: string;
  updated_at: string;
};

/** Страница списка изданий: общее число и выданные строки. */
export type BookPage = { total: number; limit: number; offset: number; items: Book[] };

/** По какому столбцу упорядочен список книг. Значения — те же, что
 *  принимает API: второй набор здесь разошёлся бы с ним молча. */
export type BookSort = "code" | "title" | "updated";

export type SortOrder = "asc" | "desc";

/** Зачем файл в комплекте книги.
 *
 * Роль назначается человеком: по формату её не угадать — PDF бывает и
 * единственным источником текста, и визуальным эталоном при EPUB.
 */
export type SourceRole = "primary_text" | "visual_reference" | "auxiliary" | "code_source";

/** Что сервис смог прочитать в файле.
 *
 * Название и автор — так, как их объявляет сам файл: по ним сличают
 * источники между собой.
 */
export type SourceValidation = {
  format_ok: boolean;
  has_text_layer: boolean;
  page_count: number | null;
  meta_title: string | null;
  meta_author: string | null;
  parser_version: string;
  warnings: string[];
  updated_at: string;
};

/** Файл в комплекте книги. Проверки может не быть: она запускается
 *  отдельно, потому что на большом PDF занимает время. */
export type BookSource = {
  id: string;
  title: string;
  original_filename: string | null;
  source_format: string;
  source_role: SourceRole | null;
  size_bytes: number | null;
  content_hash: string | null;
  validation: SourceValidation | null;
};

/** Комплект исходников книги и предупреждение о разных изданиях.
 *
 * Предупреждение — именно предупреждение: у правильного комплекта
 * названия тоже расходятся (перевод, подзаголовок, серия), и решение
 * принимает человек.
 */
export type BookKit = { sources: BookSource[]; mismatch: string | null };

/** Утверждены ли границы главы. */
export type BoundaryStatus = "draft" | "approved";

/** Откуда взялись границы: по заголовкам, по файлам EPUB, по страницам
 *  PDF, весь документ целиком — или их выставил человек. */
export type ChapterOrigin = "heading" | "path" | "page" | "whole" | "manual";

/** Раздел главы: подзаголовок и состав до следующего подзаголовка.
 *  По началу раздела (`start`) главу делят. */
export type ChapterSection = {
  start: number;
  end: number;
  level: number | null;
  title: string | null;
  locator: Record<string, string | number>;
  kinds: Record<string, number>;
};

/** Глава книги.
 *
 * Код пуст, пока границы не утверждены ни разу: он выдаётся при
 * утверждении и дальше не меняется. Место (`ordinal`) меняется при
 * разделении и объединении глав выше — потому они и разные поля.
 */
export type Chapter = {
  id: string;
  book_id: string;
  code: string | null;
  ordinal: number;
  title: string | null;
  source_start: number;
  source_end: number;
  parser_version: string;
  locator: Record<string, string | number>;
  origin: ChapterOrigin;
  boundary_status: BoundaryStatus;
  boundary_version: number;
  approved_by_id: string | null;
  approved_at: string | null;
  sections: ChapterSection[];
  inventory: Record<string, number>;
};

/** Структура книги: главы и файл, по которому они размечены. */
export type BookStructure = {
  chapters: Chapter[];
  source: {
    id: string;
    title: string;
    original_filename: string | null;
    source_format: string;
  } | null;
  // Ложно, если основной источник сменили после разметки.
  source_is_primary: boolean;
  // Заново предложить можно, пока ни одна глава не получила кода.
  can_propose: boolean;
};

export type DocumentStatus =
  | "uploaded"
  | "parsing"
  | "parsed"
  | "translating"
  | "review"
  | "done"
  | "failed";

/** Во что собирается перевод: формат оригинала, если он переписывается по
 *  месту, и текстовые — для любого исходника. Список приходит от API:
 *  реестр сборщиков живёт там, и второй список здесь разошёлся бы с ним. */
export type ExportFormat = "source" | "docx" | "markdown" | "text";

export type Document = {
  id: string;
  project_id: string;
  // Книга, в комплект которой входит файл, и его роль в нём. Пусто, пока
  // файл просто загружен в проект.
  book_id: string | null;
  source_role: SourceRole | null;
  title: string;
  original_filename: string | null;
  source_format: string;
  export_formats: ExportFormat[];
  status: DocumentStatus;
  size_bytes: number | null;
  content_hash: string | null;
  error: string | null;
  input_tokens: number;
  output_tokens: number;
  cached_input_tokens: number;
  cache_write_tokens: number;
  translated_by: string | null;
  created_at: string;
  updated_at: string;
};

export type DocumentProfile = {
  segments: number;
  characters: number;
  words: number;
  longest_segment_chars: number;
  by_kind: Record<string, number>;
  by_status: Record<string, number>;
  untranslated: number;
  unique_untranslated: number;
  repeated: number;
  memory_matches: number;
  terms_total: number;
  undecided_terms: number;
  billable_texts: number;
  billable_characters: number;
  estimate: { input_tokens: number; output_tokens: number; usd: number | null } | null;
};

export type Finding = { check: string; message: string };

export type Segment = {
  id: string;
  position: number;
  kind: string;
  status: string;
  source_text: string;
  target_text: string | null;
  source_location: Record<string, unknown> | null;
  quality: { findings?: Finding[] } | null;
  quality_score: number | null;
  translation_source: string | null;
};

export type JobState = "waiting" | "running" | "done" | "failed" | "cancelled";

/** Задание на перевод книги — работа, которая идёт без человека. */
export type TranslationJob = {
  id: string;
  document_id: string;
  // Название книги — с заданием: список заданий читают люди.
  document_title: string;
  state: JobState;
  requested_by_id: string | null;
  attempts: number;
  error: string | null;
  // Факты запуска: сколько было непереведённого, когда взялись, и сколько
  // перевели с тех пор. Не состояние документа — оно считается отдельно.
  segments_total: number;
  segments_done: number;
  started_at: string | null;
  finished_at: string | null;
  notified_at: string | null;
  created_at: string;
  updated_at: string;
};

/** Состояние книги для очереди замечаний и полосы выполнения. */
export type ReviewProgress = {
  total: number;
  translated: number;
  flagged: number;
  edited: number;
  approved: number;
  untouched: number;
  is_complete: boolean;
  // Чего ждёт очередь по видам проверок. Считается по всей книге, а не по
  // выданной странице: по этому числу судят об оставшейся работе.
  by_check: Record<string, number>;
};

export type Role = "owner" | "admin" | "manager" | "translator" | "reviewer" | "viewer";

export type Member = {
  user_id: string;
  email: string;
  full_name: string | null;
  role: Role;
  last_login_at: string | null;
  joined_at: string;
};

/** Открытое приглашение. Ссылки в нём нет: в базе только её хеш, и после
 *  выписки она показывается один раз. */
export type Invitation = {
  id: string;
  email: string;
  role: Role;
  invited_by: string | null;
  created_at: string;
  expires_at: string;
  expired: boolean;
};

export type Team = {
  members: Member[];
  invitations: Invitation[];
  // Роль смотрящего: по ней решается, показывать ли управление.
  my_role: Role;
};

export type SegmentPage = {
  total: number;
  limit: number;
  offset: number;
  items: Segment[];
};

export type GlossaryKind = "term" | "abbreviation" | "do_not_translate" | "notation" | "proper_name";

export type GlossaryStatus =
  | "proposed"
  | "confirmed"
  | "needs_review"
  | "needs_unification"
  | "retired";

/** Запись словаря: разряд — что это, статус — договорились ли. */
export type GlossaryTerm = {
  id: string;
  project_id: string | null;
  source_language: string;
  target_language: string;
  source_term: string;
  target_term: string;
  kind: GlossaryKind;
  status: GlossaryStatus;
  note: string | null;
  reference: string | null;
  mandatory: boolean;
  case_sensitive: boolean;
  expand_on_first_use: boolean;
  // «manual», «extracted», «platform», «import:<источник>».
  source: string;
  upload_id: string | null;
  created_at: string;
  updated_at: string;
};

export type GlossaryPage = { total: number; items: GlossaryTerm[] };

/** Запись о загрузке словаря — с разрешением, под которым она прошла. */
export type GlossaryUpload = {
  id: string;
  filename: string;
  origin: string;
  source_language: string;
  target_language: string;
  project_id: string | null;
  total: number;
  added: number;
  updated: number;
  skipped: number;
  shared: boolean;
  created_at: string;
};

/** Термин общего словаря площадки. */
export type SharedTerm = {
  id: string;
  subject: string;
  source_language: string;
  target_language: string;
  source_term: string;
  target_term: string;
  kind: GlossaryKind;
  note: string | null;
  created_at: string;
};

/** Подсказки из общего словаря; без тематики их нет — и сказано почему. */
export type Suggestions = { subject: string | null; items: SharedTerm[] };

/** Пара памяти переводов: «этот исходник переведён вот так». */
export type TranslationUnit = {
  id: string;
  source_language: string;
  target_language: string;
  source_text: string;
  target_text: string;
  // Имя модели либо «human».
  origin: string;
  // Сколько раз пара пригодилась — то есть сколько раз за неё не платили.
  hits: number;
  created_at: string;
  updated_at: string;
};

/** Чего память стоит. Деньги — оценка сверху по текущей модели. */
export type MemorySummary = {
  units: number;
  human_units: number;
  hits: number;
  saved_characters: number;
  saved_usd: number | null;
};

export type MemoryPage = { total: number; items: TranslationUnit[]; summary: MemorySummary };

export type CatalogReference = { title: string; url: string };

/** Справка по термину: что это, какой перевод предлагают источники. */
export type CatalogEntry = {
  id: string;
  source_language: string;
  target_language: string;
  source_term: string;
  // Ложь — тоже результат: искали и не нашли, второй раз спрашивать незачем.
  found: boolean;
  suggested_target: string | null;
  definition: string | null;
  expansion: string | null;
  kind: GlossaryKind;
  sources: CatalogReference[];
  // Имя модели, ходившей в сеть, либо «offline».
  looked_up_by: string;
  checked_at: string;
};

/** Чем отвечает справочник сейчас. */
export type CatalogSource = { name: string; online: boolean };

/** Сегмент в выдаче поиска — с книгой, в которой он стоит. */
export type SegmentHit = {
  id: string;
  document_id: string;
  document_title: string;
  position: number;
  kind: string;
  status: string;
  source_text: string;
  target_text: string | null;
};

/** Общий поиск: четыре группы, в каждой общее число и первые несколько. */
export type SearchResult = {
  query: string;
  documents: { total: number; items: Document[] };
  terms: { total: number; items: GlossaryTerm[] };
  entries: { total: number; items: CatalogEntry[] };
  segments: { total: number; items: SegmentHit[] };
};

/** Чем закончился запрос справок. */
export type CatalogLookupReport = {
  entries: CatalogEntry[];
  from_catalog: number;
  asked: number;
  found: number;
  searches: number;
  estimated_usd: number | null;
};

/** Ответ API — или причина, по которой его нет.
 *
 * Отказ возвращается страницей, а не бросается: недоступный API это не
 * «страница сломалась», а «сейчас не показать», и человеку надо сказать
 * именно это. Исключение — истёкший сеанс: он уводит на продление, потому
 * что показывать вошедшему сообщение об ошибке вместо его данных нечестно.
 */
export type Loaded<T> = { data: T; error?: undefined } | { data?: undefined; error: string };

export async function load<T>(path: string, returnTo: string): Promise<Loaded<T>> {
  const token = await accessToken();

  if (token === undefined) {
    redirect("/login");
  }

  try {
    return { data: await apiFetch<T>(path, { token, organizationId: await organizationId() }) };
  } catch (error) {
    if (unauthorized(error)) {
      redirect(renewUrl(returnTo));
    }

    return { error: error instanceof Error ? error.message : "Сервис недоступен" };
  }
}
