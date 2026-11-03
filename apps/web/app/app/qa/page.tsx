import type { Metadata } from "next";
import Link from "next/link";

import {
  load,
  type BookPage,
  type IssueCategory,
  type IssueSeverity,
  type QAFinding,
  type QAFindingPage,
  type QAKind,
} from "../../lib/work";
import {
  ISSUE_CATEGORY_LABEL,
  ISSUE_CATEGORY_ORDER,
  ISSUE_SEVERITY_CHIP,
  ISSUE_SEVERITY_LABEL,
  ISSUE_SEVERITY_ORDER,
  ISSUE_STATUS_CHIP,
  ISSUE_STATUS_LABEL,
  QA_CHECK_LABEL,
  QA_RULE_LABEL,
  plural,
  thousands,
  when,
} from "../labels";
import "../work.css";
import "../ui/ui.css";
import "../issues/issues.css";
import { CopyId } from "../ui/copy-id";
import { Pager } from "../ui/pager";
import { linkTo, oneOf, paramsOf, wholeNumber } from "../ui/query";
import { DataTable, type Column } from "../ui/table";

export const metadata: Metadata = {
  title: "Очередь проверок — BookTranslate",
  description: "Находки формальных проверок и смысловой сверки: замечание или правило, почему его нет.",
};

/* Очередь проверок.

   Каждая находка чем-то кончилась: за ней стоит замечание реестра или названо правило, по которому
   регистрировать незачем. Решения принимаются в реестре, а здесь видно, что нашли проверки. */

const HERE = "/app/qa";
const PER_PAGE = 50;
const OFFSET_MAX = 100000;

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const KINDS = ["", "deterministic", "semantic"] as const;
const CHECKS = ["", ...Object.keys(QA_CHECK_LABEL)];

function uuidOf(value: string | null): string | null {
  return value !== null && UUID.test(value) ? value : null;
}

export default async function QAPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = paramsOf(await searchParams);

  const book = uuidOf(params.get("book"));
  const chapter = uuidOf(params.get("chapter"));
  const kind = oneOf<QAKind | "">(params.get("kind"), KINDS, "");
  const check = oneOf(params.get("check"), CHECKS, "");
  const severity = oneOf<IssueSeverity | "">(params.get("severity"), ["", ...ISSUE_SEVERITY_ORDER], "");
  const category = oneOf<IssueCategory | "">(params.get("category"), ["", ...ISSUE_CATEGORY_ORDER], "");
  const offset = wholeNumber(params.get("offset"), 0, OFFSET_MAX);

  const filter = new URLSearchParams();

  if (book !== null) filter.set("book_id", book);
  if (chapter !== null) filter.set("chapter_id", chapter);
  if (kind !== "") filter.set("kind", kind);
  if (check !== "") filter.set("check", check);
  if (severity !== "") filter.set("severity", severity);
  if (category !== "") filter.set("category", category);

  const [findings, books] = await Promise.all([
    load<QAFindingPage>(`/qa/findings?${filter}&limit=${PER_PAGE}&offset=${offset}`, HERE),
    load<BookPage>("/books?limit=200", HERE),
  ]);

  if (findings.error !== undefined) {
    return (
      <section className="tile">
        <h2>Очередь проверок</h2>
        <p className="tile__empty">{findings.error}</p>
      </section>
    );
  }

  return (
    <>
      <header className="wk-head">
        <div>
          <h1>Очередь проверок</h1>
          <p className="tile__note">
            Что нашли проверки. Текст они не меняют: находка становится замечанием реестра, и решает
            человек. Запуск — на странице главы.
          </p>
        </div>
      </header>

      <section className="tile">
        <form className="is-filters" method="get" action={HERE}>
          {chapter !== null && <input type="hidden" name="chapter" value={chapter} />}

          <label className="field">
            <span>Книга</span>
            <select name="book" defaultValue={book ?? ""}>
              <option value="">Все книги</option>
              {books.data?.items.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.code} · {item.title}
                </option>
              ))}
            </select>
          </label>

          <label className="field">
            <span>Вид проверки</span>
            <select name="kind" defaultValue={kind}>
              <option value="">Любой</option>
              <option value="deterministic">Формальная</option>
              <option value="semantic">Смысловая</option>
            </select>
          </label>

          <label className="field">
            <span>Проверка</span>
            <select name="check" defaultValue={check}>
              <option value="">Любая</option>
              {Object.entries(QA_CHECK_LABEL).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>

          <label className="field">
            <span>Серьёзность</span>
            <select name="severity" defaultValue={severity}>
              <option value="">Любая</option>
              {ISSUE_SEVERITY_ORDER.map((item) => (
                <option key={item} value={item}>
                  {ISSUE_SEVERITY_LABEL[item]}
                </option>
              ))}
            </select>
          </label>

          <label className="field is-filters__query">
            <span>Категория</span>
            <select name="category" defaultValue={category}>
              <option value="">Любая</option>
              {ISSUE_CATEGORY_ORDER.map((item) => (
                <option key={item} value={item}>
                  {ISSUE_CATEGORY_LABEL[item]}
                </option>
              ))}
            </select>
          </label>

          <button className="btn btn--ghost" type="submit">
            Показать
          </button>
        </form>

        {chapter !== null && (
          <div className="is-filters__foot">
            <Link
              className="btn btn--ghost btn--small"
              href={linkTo(HERE, params, { chapter: null, offset: null })}
            >
              Снять отбор по главе
            </Link>
          </div>
        )}
      </section>

      <section className="tile">
        <div className="tile__head">
          <h3>Находки</h3>
          <span className="tile__note">
            {thousands(findings.data.total)}{" "}
            {plural(findings.data.total, "находка", "находки", "находок")}
          </span>
        </div>

        <DataTable
          caption="Находки проверок"
          columns={COLUMNS}
          rows={findings.data.items}
          empty="Под этот отбор ничего не подошло. Проверки запускаются на странице главы."
        />
        <Pager
          total={findings.data.total}
          limit={PER_PAGE}
          offset={offset}
          path={HERE}
          params={params}
        />
      </section>
    </>
  );
}

const COLUMNS: Column<QAFinding>[] = [
  {
    title: "Блок",
    cell: (row) => (
      <Link
        className="wk-link"
        href={`/app/books/${row.book_id}/chapters/${row.chapter_id}/translation/${row.block_id}`}
      >
        {row.block_code}
      </Link>
    ),
  },
  {
    title: "Что нашли",
    cell: (row) => (
      <>
        <span className="is-description">{row.message}</span>
        <span className="tile__note">{QA_CHECK_LABEL[row.check] ?? row.check}</span>
      </>
    ),
  },
  {
    title: "Серьёзность",
    cell: (row) => (
      <span className={ISSUE_SEVERITY_CHIP[row.severity]}>{ISSUE_SEVERITY_LABEL[row.severity]}</span>
    ),
  },
  {
    title: "Итог",
    cell: (row) =>
      row.issue_id !== null && row.issue_code !== null && row.issue_status !== null ? (
        <span className="bk-block-id">
          <CopyId value={row.issue_code} title="код ошибки" />
          <Link href={`/app/issues/${row.issue_id}`}>
            <span className={ISSUE_STATUS_CHIP[row.issue_status]}>
              {ISSUE_STATUS_LABEL[row.issue_status]}
            </span>
          </Link>
        </span>
      ) : (
        <span className="tile__note">
          Не требует регистрации: {QA_RULE_LABEL[row.rule ?? ""] ?? row.rule}
        </span>
      ),
  },
  {
    title: "Когда",
    secondary: true,
    cell: (row) => when(row.created_at),
  },
];
