/* Данные работы: проекты, книги, главы, редакции.

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
export type BookKit = {
  sources: BookSource[];
  mismatch: string | null;
  /** Во что собирается черновая выгрузка книги: реестр сборщиков живёт в API. */
  export_formats: ExportFormat[];
  blocks: number;
  translated: number;
};

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

/** Версия мастера главы — неизменяемый снимок её исходного текста.
 *
 * Текст мастера не правится никогда: ошибка извлечения исправляется
 * новой версией с причиной. Поэтому у версии нет «изменить», есть только
 * «утвердить» — подтвердить, что извлечено верно.
 */
export type ChapterMaster = {
  id: string;
  chapter_id: string;
  version: number;
  label: string;
  supersedes_id: string | null;
  reason: string | null;
  source_document_id: string;
  parser_version: string;
  boundary_version: number;
  block_count: number;
  object_count: number;
  checksum: string;
  created_by_id: string | null;
  approved_by_id: string | null;
  approved_at: string | null;
  created_at: string;
};

export type ObjectType = "figure" | "table" | "equation" | "code";

/** Дерево формулы MathML для показа: `[тег, {атрибуты}, ...дети]`.
 *  Теги и атрибуты в нём — только разрешённые: перечень закрыт в API. */
export type MathTree = [string, Record<string, string>, ...(MathTree | string)[]];

/** Изображение рисунка. Суммы нет — изображение в исходнике не нашлось. */
export type ObjectImage = {
  sha256: string | null;
  media_type: string | null;
  size: number | null;
  src: string | null;
  alt: string | null;
};

export type TableCell = {
  row: number;
  col: number;
  rowspan: number;
  colspan: number;
  header: boolean;
};

/** Содержимое объекта по виду: изображения рисунка, сетка таблицы,
 *  запись и дерево формулы, язык листинга. */
export type ObjectPayload = {
  images?: ObjectImage[];
  rows?: number;
  cols?: number;
  cells?: TableCell[];
  notation?: "mathml" | "omml";
  text?: string;
  preview?: MathTree | null;
  normalized?: string;
  // Запись формулы как есть — только в карточке объекта.
  raw?: string;
  language?: string | null;
};

/** Рисунок, таблица, формула или листинг в составе версии мастера.
 *  `at` — сколько блоков версии стоит перед объектом. */
export type BookObject = {
  id: string;
  chapter_id: string;
  code: string;
  full_code: string;
  type: ObjectType;
  label: string | null;
  checksum: string;
  active: boolean;
  at: number;
  before_code: string | null;
  caption: string | null;
  caption_code: string | null;
  content_codes: string[];
  references: number;
  payload: ObjectPayload;
};

/** Блок, относящийся к объекту: ячейка, листинг, подпись, упоминание. */
export type BlockRef = {
  id: string;
  code: string;
  full_code: string;
  kind: string;
  text: string;
  active: boolean;
  row: number | null;
  column: number | null;
  /** Текущая редакция перевода. Пусто, пока блок не переведён. */
  translation?: string | null;
};

export type ObjectMention = {
  block: BlockRef;
  chapter_id: string;
  kind: "link" | "label";
  phrase: string;
};

/** Отметка «проверено технически»: действует, пока не изменилось содержимое. */
export type ObjectVerification = {
  verified: boolean;
  verified_at: string | null;
  verified_by: string | null;
  outdated: boolean;
};

export type ObjectDetail = BookObject & {
  verification: ObjectVerification;
  book_id: string;
  master_id: string;
  master_label: string;
  content: BlockRef[];
  caption_block: BlockRef | null;
  mentions: ObjectMention[];
  parent_code: string | null;
};

export type FoundObject = {
  book_id: string;
  book_code: string;
  chapter_id: string;
  object_id: string;
  full_code: string;
};

/** Блок главы с постоянным кодом. `ordinal` — место в показываемой
 *  версии мастера; `parent_code` — блок, из которого этот получился. */
export type Block = {
  id: string;
  chapter_id: string;
  code: string;
  full_code: string;
  kind: string;
  ordinal: number;
  source_text: string;
  source_location: Record<string, string | number>;
  source_hash: string;
  active: boolean;
  parent_code: string | null;
  chunks: number;
};

export type BlockPage = { total: number; limit: number; offset: number; items: Block[] };

/** Блок, найденный по коду, и где его показать. `position` пуст, если
 *  блок выведен из действия и живёт только в прежних версиях. */
export type FoundBlock = {
  book_id: string;
  book_code: string;
  chapter_id: string;
  block: Block;
  position: number | null;
};

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

/** Смета главы: из чего она состоит и во что обойдётся. */
export type ChapterEstimate = {
  blocks: number;
  characters: number;
  words: number;
  longest_block_chars: number;
  by_kind: Record<string, number>;
  untranslated: number;
  protected: number;
  unique_untranslated: number;
  repeated: number;
  book_matches: number;
  memory_matches: number;
  billable_texts: number;
  billable_characters: number;
  estimate: { input_tokens: number; output_tokens: number; usd: number | null } | null;
};

export type JobState = "waiting" | "running" | "done" | "failed" | "cancelled";

/** Задание на перевод книги — работа, которая идёт без человека. */
export type TranslationJob = {
  id: string;
  kind: "chapter" | "qa" | "render" | "figures";
  chapter_id: string | null;
  book_release_id: string | null;
  book_id: string;
  run_id: string | null;
  qa_run_id: string | null;
  // Название книги — с заданием: список заданий читают люди.
  title: string;
  state: JobState;
  requested_by_id: string | null;
  attempts: number;
  error: string | null;
  // Факты запуска: сколько было непереведённого, когда взялись, и сколько
  // перевели с тех пор. Не состояние документа — оно считается отдельно.
  items_total: number;
  items_done: number;
  started_at: string | null;
  finished_at: string | null;
  notified_at: string | null;
  created_at: string;
  updated_at: string;
};

export type RevisionOrigin = "model" | "memory" | "human" | "copy";
export type RevisionStage = "draft" | "working" | "final_candidate";

/** Блок, ответ по которому отвергнут: остался без редакции. */
export type RunRejection = { block_id: string; code: string; reason: string };

/** Прогон перевода: чем и по чему переводили, как идёт и сколько стоил. */
export type TranslationRun = {
  id: string;
  chapter_id: string;
  master_id: string;
  kind: "draft" | "retranslate";
  provider: string;
  model: string;
  prompt_version: string;
  glossary_version_id: string | null;
  glossary_label: string | null;
  ignore_terminology: boolean;
  bypass_reason: string | null;
  requested_by_id: string | null;
  job_id: string | null;
  state: JobState | null;
  error: string | null;
  blocks_total: number;
  blocks_done: number;
  from_model: number;
  from_memory: number;
  copied: number;
  rejections: RunRejection[];
  input_tokens: number;
  output_tokens: number;
  cached_input_tokens: number;
  cache_write_tokens: number;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
};

/** Можно ли переводить главу и что об этом известно. */
export type ChapterTranslation = {
  chapter_id: string;
  open: boolean;
  bypassable: boolean;
  blockers: GateItem[];
  warnings: GateItem[];
  glossary_version_id: string | null;
  glossary_label: string | null;
  master_id: string | null;
  master_label: string | null;
  total: number;
  translated: number;
  pending: number;
  live: TranslationRun | null;
  latest: TranslationRun | null;
};

export type RevisionBrief = {
  id: string;
  revision_no: number;
  stage: RevisionStage;
  origin: RevisionOrigin;
  text: string;
  created_at: string;
};

export type ChapterBlock = {
  id: string;
  code: string;
  ordinal: number;
  kind: string;
  source_text: string;
  protected: boolean;
  current: RevisionBrief | null;
  variants: number;
  formal_checked: boolean;
  semantic_checked: boolean;
};

export type ChapterBlockPage = { total: number; items: ChapterBlock[] };

export type RevisionChange = { op: "equal" | "insert" | "delete"; text: string };

export type BlockRevision = {
  id: string;
  block_id: string;
  revision_no: number;
  stage: RevisionStage;
  origin: RevisionOrigin;
  text: string;
  current: boolean;
  supersedes_id: string | null;
  copied_from_id: string | null;
  memory_unit_id: string | null;
  run_id: string | null;
  run_kind: "draft" | "retranslate" | null;
  model: string | null;
  prompt_version: string | null;
  glossary_version_id: string | null;
  glossary_label: string | null;
  ignore_terminology: boolean;
  author: string | null;
  edit_reason: EditReason | null;
  issue_id: string | null;
  formal_checked: boolean;
  semantic_checked: boolean;
  compared_with: number | null;
  changes: RevisionChange[];
  created_at: string;
};

export type RevisionHistory = {
  block_id: string;
  code: string;
  source_text: string;
  active: boolean;
  protected: boolean;
  items: BlockRevision[];
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
  // Согласованные варианты перевода помимо основного.
  allowed_variants: string[];
  // Предметная область, где решение верно.
  domain: string | null;
  kind: GlossaryKind;
  status: GlossaryStatus;
  note: string | null;
  reference: string | null;
  mandatory: boolean;
  case_sensitive: boolean;
  first_use_rule: FirstUseRule;
  // «manual», «extracted», «platform», «import:<источник>».
  source: string;
  upload_id: string | null;
  created_at: string;
  updated_at: string;
};

export type GlossaryPage = { total: number; items: GlossaryTerm[] };

/** Что сделать с термином при первом употреблении. */
export type FirstUseRule = "none" | "expand" | "original";

/** Кандидат в словарь — вопрос «как это называть», а не термин. */
export type TermCandidate = {
  id: string;
  document_id: string | null;
  chapter_id: string | null;
  source_term: string;
  kind: GlossaryKind;
  status: "new" | "accepted" | "rejected";
  frequency: number;
  sample: string;
  first_position: number;
  first_block_id: string | null;
  // `CH03-B0042` — у кандидатов главы.
  first_block_code: string | null;
  expansion: string | null;
  glossary_term_id: string | null;
};

export type GlossaryVersionStatus = "draft" | "approved" | "superseded";

/** Версия глоссария — неизменяемый снимок словаря с решением по нему. */
export type GlossaryVersion = {
  id: string;
  book_id: string;
  // Пусто у книжной версии.
  chapter_id: string | null;
  scope: "book" | "chapter";
  number: number;
  label: string;
  status: GlossaryVersionStatus;
  base_id: string | null;
  superseded_by_id: string | null;
  checksum: string;
  term_count: number;
  empty_reason: string | null;
  created_by_id: string | null;
  created_at: string;
  approved_by_id: string | null;
  approved_at: string | null;
};

/** Причина гейта: код — для машины, фраза — для человека. */
export type GateItem = {
  code: string;
  message: string;
  chapter_id: string | null;
  count: number | null;
};

export type GlossaryVersionDetail = GlossaryVersion & {
  chapter_code: string | null;
  blockers: GateItem[];
  changes: number;
  impacted_blocks: number;
};

export type TerminologyPass = {
  id: string;
  master_id: string;
  actor_id: string | null;
  min_frequency: number;
  found: number;
  created_at: string;
};

/** Готова ли глава к переводу с точки зрения терминов. */
export type TerminologyGate = {
  chapter_id: string;
  chapter_code: string | null;
  chapter_title: string | null;
  ordinal: number;
  open: boolean;
  version: GlossaryVersion | null;
  draft: GlossaryVersion | null;
  blockers: GateItem[];
  warnings: GateItem[];
  master_id: string | null;
  current_pass: TerminologyPass | null;
  collected: boolean;
  undecided: number;
};

export type BookTerminology = { chapters: TerminologyGate[]; versions: GlossaryVersion[] };

/** Термин в снимке версии — таким, каким его утвердили. */
export type VersionTerm = {
  id: string;
  term_id: string | null;
  source_term: string;
  target_term: string;
  allowed_variants: string[];
  kind: GlossaryKind;
  status: GlossaryStatus;
  mandatory: boolean;
  case_sensitive: boolean;
  first_use_rule: FirstUseRule;
  domain: string | null;
  note: string | null;
  reference: string | null;
};

export type VersionTermPage = { total: number; items: VersionTerm[] };

/** Прежнее или новое решение по термину — как оно записано в версии. */
export type TermRecord = Omit<VersionTerm, "id" | "term_id">;

export type TermChange = {
  id: string;
  source_term: string;
  kind: "added" | "changed" | "removed";
  before: TermRecord | null;
  after: TermRecord | null;
  blocks: number;
};

export type ImpactedBlock = {
  block: BlockRef;
  chapter_id: string;
  chapter_code: string | null;
  terms: string[];
};

export type ImpactPage = { total: number; items: ImpactedBlock[] };

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

/* Перевод надписей на рисунках. */

export type FigureStatus = "draft" | "approved" | "kept_original" | "no_text";

export type FigureRegion = {
  id: string;
  x: number;
  y: number;
  w: number;
  h: number;
  source_text: string;
  target_text: string | null;
  confidence: number;
  origin: string | null;
  overflow: boolean;
};

export type FigureTranslation = {
  id: string;
  version: number;
  status: FigureStatus;
  regions: FigureRegion[];
  needs_human: boolean;
  note: string | null;
  has_asset: boolean;
  decided_at: string | null;
};

export type FigureImage = {
  object_id: string;
  code: string;
  index: number;
  media_type: string;
  current: FigureTranslation | null;
};

export type ChapterFigures = {
  images: FigureImage[];
  undecided: number;
  job_state: JobState | null;
  job_error: string | null;
};

/* Финальные версии глав и выпуски книги. */

export type ReleaseGate = {
  ready: boolean;
  blockers: { code: string; message: string; count: number | null }[];
};

export type ChapterRelease = {
  id: string;
  book_id: string;
  chapter_id: string;
  code: string;
  version: string;
  status: "draft" | "approved";
  manifest_hash: string;
  blocks: number;
  objects: number;
  creator: string | null;
  approver: string | null;
  approved_at: string | null;
  created_at: string;
  // Рабочий текст ушёл вперёд от этой версии.
  working_differs: boolean;
};

export type WorkingChange = {
  block_id: string;
  code: string;
  final_text: string | null;
  working_text: string | null;
  changes: RevisionChange[];
};

export type Assembly = {
  ready: boolean;
  items: {
    chapter_id: string;
    chapter_code: string | null;
    title: string | null;
    ordinal: number;
    chosen_id: string | null;
    available: { id: string; code: string; version: string }[];
    working_differs: boolean;
  }[];
  problems: {
    code: string;
    severity: "blocker" | "warning";
    message: string;
    chapter_id: string | null;
  }[];
  toc: { chapter_code: string | null; level: number; text: string }[];
};

export type BookRelease = {
  id: string;
  book_id: string;
  title: string;
  code: string;
  version: string;
  status: "built" | "passed";
  manifest_hash: string;
  chapters: { position: number; release_id: string; release_code: string; title: string | null }[];
  toc: { chapter_code: string | null; level: number; text: string }[];
  created_at: string;
  created: boolean;
};

export type ReleaseArtifact = {
  id: string;
  format: "docx" | "pdf";
  checksum: string;
  size: number;
  renderer_version: string;
  manifest_hash: string;
  page_count: number | null;
  superseded_at: string | null;
  created_at: string;
};

export type ReleaseFiles = {
  artifacts: ReleaseArtifact[];
  previous: ReleaseArtifact[];
  job_state: JobState | null;
  job_error: string | null;
};

export type PageAudit = {
  page_no: number;
  status: "unreviewed" | "pass" | "issue" | "stale";
  issue_id: string | null;
  checked_at: string | null;
};

export type ReleaseControl = {
  release_id: string;
  code: string;
  status: "built" | "passed";
  ready: boolean;
  checks: { code: string; title: string; passed: boolean }[];
  blockers: {
    check: string;
    code: string;
    message: string;
    count: number | null;
    chapter_id: string | null;
    issue_id: string | null;
    page_no: number | null;
  }[];
  passed_at: string | null;
};

/* Редактура и финальная сверка. */

export type ReviewKind = "technical" | "literary" | "final_compare";
export type ReviewMark = "ok" | "issue";
export type EditReason = "style" | "calque" | "readability";

export type ReviewRun = {
  id: string;
  book_id: string;
  book_title: string;
  chapter_id: string;
  chapter_title: string | null;
  kind: ReviewKind;
  status: "open" | "completed";
  reviewer: string | null;
  base_revision_set_hash: string;
  completed_revision_set_hash: string | null;
  completed_at: string | null;
  created_at: string;
  // Текст изменился после завершения: эта работа была про другой текст.
  stale: boolean;
  blocks_total: number;
  blocks_done: number;
  objects_total: number;
  objects_done: number;
  untranslated: number;
  complete: boolean;
};

export type ChapterReviews = {
  technical: ReviewRun | null;
  literary: ReviewRun | null;
  final_compare: ReviewRun | null;
};

export type ReviewOpenIssue = {
  id: string;
  code: string;
  severity: IssueSeverity;
  status: IssueStatus;
};

export type ReviewNextBlock = {
  id: string;
  code: string;
  ordinal: number;
  kind: string;
  source_text: string;
  revision_id: string;
  revision_no: number;
  text: string;
  protected: boolean;
  context: { code: string; ordinal: number; source_text: string; translation: string | null }[];
  terms: { source: string; target: string; mandatory: boolean }[];
  objects: {
    id: string;
    chapter_id: string;
    code: string;
    type: string;
    relation: string;
  }[];
  issues: ReviewOpenIssue[];
};

export type ReviewNextObject = {
  id: string;
  code: string;
  type: string;
  content_hash: string;
  position: number;
  source_text: string;
  translation: string | null;
  issues: ReviewOpenIssue[];
};

/** Оба поля пусты: просмотрено всё. */
export type ReviewNext = { block: ReviewNextBlock | null; object: ReviewNextObject | null };

/* Проверки. */

export type QAKind = "deterministic" | "semantic";

export type QARun = {
  id: string;
  chapter_id: string;
  kind: QAKind;
  scope: "risky" | "all";
  check_profile_version: string;
  revision_set_hash: string;
  model: string | null;
  blocks_total: number;
  blocks_checked: number;
  blocks_untranslated: number;
  findings_total: number;
  issues_created: number;
  rejections: { block_id: string; code: string; reason: string }[];
  input_tokens: number;
  output_tokens: number;
  job_id: string | null;
  state: JobState | null;
  error: string | null;
  created_at: string;
};

export type ChapterChecks = {
  total: number;
  translated: number;
  formal: number;
  semantic: number;
  revision_set_hash: string;
  latest_formal: QARun | null;
  latest_semantic: QARun | null;
  live: QARun | null;
  semantic_scope: "risky" | "all";
};

export type QAFinding = {
  id: string;
  qa_run_id: string;
  book_id: string;
  chapter_id: string;
  block_id: string;
  block_code: string;
  revision_id: string;
  kind: QAKind;
  check: string;
  message: string;
  category: IssueCategory;
  severity: IssueSeverity;
  disposition: "registered" | "not_required";
  rule: string | null;
  issue_id: string | null;
  issue_code: string | null;
  issue_status: IssueStatus | null;
  created_at: string;
};

export type QAFindingPage = { total: number; items: QAFinding[] };

/* Реестр ошибок. */

export type IssueCategory =
  | "translation"
  | "terminology"
  | "semantic"
  | "number"
  | "formula"
  | "table"
  | "figure"
  | "code"
  | "technical"
  | "style"
  | "cross_reference"
  | "source_error"
  | "layout";

export type IssueSeverity = "critical" | "major" | "minor";

export type IssueStatus =
  | "new"
  | "needs_clarification"
  | "confirmed"
  | "fixed"
  | "verified"
  | "closed"
  | "rejected"
  | "reopened";

export type IssueEventKind =
  | "created"
  | "status_changed"
  | "reclassified"
  | "assigned"
  | "commented"
  | "attached"
  | "archived"
  | "restored";

export type IssueRow = {
  id: string;
  code: string;
  book_id: string;
  book_title: string;
  chapter_id: string;
  block_id: string | null;
  block_code: string | null;
  object_id: string | null;
  object_code: string | null;
  parent_issue_id: string | null;
  category: IssueCategory;
  severity: IssueSeverity;
  status: IssueStatus;
  priority_score: number;
  impact_count: number;
  automatic: boolean;
  detected_by: string | null;
  assignee_id: string | null;
  assignee: string | null;
  description: string;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
};

export type IssuePage = { total: number; items: IssueRow[] };

export type IssueStats = {
  total: number;
  by_status: Partial<Record<IssueStatus, number>>;
  by_severity: Partial<Record<IssueSeverity, number>>;
  by_category: Partial<Record<IssueCategory, number>>;
  open_critical: number;
  open_major: number;
};

export type IssueEvent = {
  id: string;
  kind: IssueEventKind;
  from_status: IssueStatus | null;
  to_status: IssueStatus | null;
  actor: string | null;
  note: string | null;
  related_revision_id: string | null;
  payload: Record<string, unknown>;
  created_at: string;
};

export type IssueCandidate = {
  revision_id: string;
  revision_no: number;
  block_code: string;
  text: string;
};

export type IssueEditable = {
  block_id: string;
  block_code: string;
  revision_id: string;
  revision_no: number;
  text: string;
};

export type RegressionKind =
  | "same_source_repeat"
  | "term_usage"
  | "object_reference"
  | "cross_reference"
  | "adjacent_context"
  | "table_caption"
  | "figure_caption";

export type RegressionDecision = "pending" | "not_affected" | "propagated" | "issue_created";

export type RegressionItem = {
  id: string;
  kind: RegressionKind;
  block_id: string | null;
  object_id: string | null;
  code: string;
  required: boolean;
  safe: boolean;
  source_text: string | null;
  current_text: string | null;
  proposed_text: string | null;
  final_candidate: boolean;
  decision: RegressionDecision;
  note: string | null;
  child_issue_id: string | null;
  child_code: string | null;
};

export type RegressionRun = {
  id: string;
  status: "open" | "completed" | "superseded";
  fix_revision_id: string;
  pending: number;
  items: RegressionItem[];
};

export type IssueBrief = { id: string; code: string; status: IssueStatus };

export type IssueDetail = IssueRow & {
  chapter_label: string | null;
  source_snapshot: string;
  target_snapshot: string | null;
  proposed_fix: string | null;
  discovered_revision_id: string | null;
  fix_revision_id: string | null;
  current_revision_id: string | null;
  current_text: string | null;
  subject_active: boolean;
  context: { block_id: string; code: string; source_text: string; translation: string | null }[];
  terms: { source: string; target: string; mandatory: boolean; note: string | null }[];
  objects: { id: string; code: string; type: string }[];
  events: IssueEvent[];
  attachments: {
    id: string;
    filename: string;
    media_type: string;
    size_bytes: number;
    created_at: string;
  }[];
  candidates: IssueCandidate[];
  editable: IssueEditable[];
  children: IssueBrief[];
  parent: IssueBrief | null;
  /** Что этому человеку можно сделать сейчас: кнопки рисуются по этому списку. */
  actions: string[];
  review_note: string | null;
};

/** Замечание в выдаче поиска. */
export type IssueHit = {
  id: string;
  code: string;
  status: IssueStatus;
  severity: IssueSeverity;
  description: string;
};

/** Блок в выдаче поиска — с книгой и главой, где он стоит. */
export type BlockHit = {
  id: string;
  book_id: string;
  book_title: string;
  chapter_id: string;
  full_code: string;
  kind: string;
  source_text: string;
  translation: string | null;
};

/** Общий поиск: четыре группы, в каждой общее число и первые несколько. */
export type SearchResult = {
  query: string;
  documents: { total: number; items: Document[] };
  terms: { total: number; items: GlossaryTerm[] };
  entries: { total: number; items: CatalogEntry[] };
  blocks: { total: number; items: BlockHit[] };
  issues: { total: number; items: IssueHit[] };
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
