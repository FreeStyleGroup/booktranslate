import type { Metadata } from "next";
import Link from "next/link";

import {
  load,
  type BookPage,
  type IssueCategory,
  type IssuePage,
  type IssueRow,
  type IssueSeverity,
  type IssueStats,
  type IssueStatus,
} from "../../lib/work";
import {
  ISSUE_CATEGORY_LABEL,
  ISSUE_CATEGORY_ORDER,
  ISSUE_SEVERITY_CHIP,
  ISSUE_SEVERITY_LABEL,
  ISSUE_SEVERITY_ORDER,
  ISSUE_STATUS_CHIP,
  ISSUE_STATUS_LABEL,
  ISSUE_STATUS_ORDER,
  plural,
  thousands,
  when,
} from "../labels";
import "../work.css";
import "../ui/ui.css";
import "./issues.css";
import { CopyId } from "../ui/copy-id";
import { Pager } from "../ui/pager";
import { linkTo, oneOf, paramsOf, wholeNumber } from "../ui/query";
import { DataTable, type Column } from "../ui/table";

export const metadata: Metadata = {
  title: "Реестр ошибок — BookTranslate",
  description: "Все найденные ошибки: постоянные коды, серьёзность, состояние и история решений.",
};

/* Реестр ошибок.

   Найденная проблема сначала попадает сюда и получает постоянный код, а исправляется только
   после подтверждения. Записи не удаляются: отклонённое остаётся в истории, решённое можно
   убрать в архив.

   Отбор, порядок и страница живут в адресе, как во всех списках кабинета. Значения сверяются
   с закрытыми наборами, и подобранное в адресе до запроса к API не доедет. */

const HERE = "/app/issues";
const PER_PAGE = 50;
const OFFSET_MAX = 100000;

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const SORTS = ["priority", "created", "severity", "status"] as const;
const ORDERS = ["asc", "desc"] as const;

// Значение отбора «Незакрытые»: это не состояние, а их группа.
const OPEN_FILTER = "open";
const OPEN_STATES: IssueStatus[] = ["new", "needs_clarification", "confirmed", "fixed", "verified", "reopened"];
const STATE_FILTERS = ["", OPEN_FILTER, ...ISSUE_STATUS_ORDER] as const;

function uuidOf(value: string | null): string | null {
  return value !== null && UUID.test(value) ? value : null;
}

export default async function IssuesPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = paramsOf(await searchParams);

  const book = uuidOf(params.get("book"));
  const chapter = uuidOf(params.get("chapter"));
  const state = oneOf(params.get("state"), STATE_FILTERS, OPEN_FILTER);
  const severity = oneOf<IssueSeverity | "">(params.get("severity"), ["", ...ISSUE_SEVERITY_ORDER], "");
  const category = oneOf<IssueCategory | "">(params.get("category"), ["", ...ISSUE_CATEGORY_ORDER], "");
  const text = (params.get("query") ?? "").trim().slice(0, 200);
  const archived = params.get("archived") === "1";
  const sort = oneOf(params.get("sort"), SORTS, "priority");
  const order = oneOf(params.get("order"), ORDERS, "desc");
  const offset = wholeNumber(params.get("offset"), 0, OFFSET_MAX);

  const filter = new URLSearchParams();

  if (book !== null) filter.set("book_id", book);
  if (chapter !== null) filter.set("chapter_id", chapter);
  if (severity !== "") filter.set("severity", severity);
  if (category !== "") filter.set("category", category);
  if (text !== "") filter.set("query", text);
  if (archived) filter.set("archived", "true");

  // В архиве только решённое: отбор «незакрытые» там дал бы пустой список без объяснения.
  if (state === OPEN_FILTER && !archived) {
    OPEN_STATES.forEach((item) => filter.append("state", item));
  } else if (state !== "" && state !== OPEN_FILTER) {
    filter.append("state", state);
  }

  const counted = new URLSearchParams();

  if (book !== null) counted.set("book_id", book);
  if (chapter !== null) counted.set("chapter_id", chapter);

  const [issues, stats, books] = await Promise.all([
    load<IssuePage>(
      `/issues?${filter}&sort=${sort}&order=${order}&limit=${PER_PAGE}&offset=${offset}`,
      HERE,
    ),
    load<IssueStats>(`/issues/stats?${counted}`, HERE),
    load<BookPage>("/books?limit=200", HERE),
  ]);

  if (issues.error !== undefined) {
    return (
      <section className="tile">
        <h2>Реестр ошибок</h2>
        <p className="tile__empty">{issues.error}</p>
      </section>
    );
  }

  return (
    <>
      <header className="wk-head">
        <div>
          <h1>Реестр ошибок</h1>
          <p className="tile__note">
            Сначала замечание получает постоянный код, и только потом его решают и исправляют.
            Записи не удаляются.
          </p>
        </div>
      </header>

      {stats.data !== undefined && <Summary stats={stats.data} />}

      <section className="tile">
        <form className="is-filters" method="get" action={HERE}>
          {chapter !== null && <input type="hidden" name="chapter" value={chapter} />}
          {archived && <input type="hidden" name="archived" value="1" />}

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
            <span>Состояние</span>
            <select name="state" defaultValue={state}>
              <option value={OPEN_FILTER}>Незакрытые</option>
              <option value="">Все</option>
              {ISSUE_STATUS_ORDER.map((item) => (
                <option key={item} value={item}>
                  {ISSUE_STATUS_LABEL[item]}
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

          <label className="field">
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

          <label className="field is-filters__query">
            <span>Код или описание</span>
            <input name="query" type="search" maxLength={200} defaultValue={text} />
          </label>

          <button className="btn btn--ghost" type="submit">
            Показать
          </button>
        </form>

        <div className="is-filters__foot">
          {chapter !== null && (
            <Link className="btn btn--ghost btn--small" href={linkTo(HERE, params, { chapter: null, offset: null })}>
              Снять отбор по главе
            </Link>
          )}
          <Link
            className="btn btn--ghost btn--small"
            href={linkTo(HERE, params, { archived: archived ? null : 1, offset: null })}
          >
            {archived ? "К действующим" : "Показать архив"}
          </Link>
          <a className="btn btn--ghost btn--small" href={`/api/issues/export?format=csv&${filter}`} download>
            Выгрузить CSV
          </a>
          <a className="btn btn--ghost btn--small" href={`/api/issues/export?format=xlsx&${filter}`} download>
            Выгрузить XLSX
          </a>
        </div>
      </section>

      <section className="tile">
        <div className="tile__head">
          <h3>{archived ? "Архив" : "Замечания"}</h3>
          <span className="tile__note">
            {thousands(issues.data.total)}{" "}
            {plural(issues.data.total, "запись", "записи", "записей")}
          </span>
        </div>

        <DataTable
          caption="Замечания реестра"
          columns={COLUMNS}
          rows={issues.data.items}
          sort={{ by: sort, descending: order === "desc", path: HERE, params }}
          empty={
            archived
              ? "В архиве пусто."
              : "Под этот отбор ничего не подошло. Ошибка регистрируется со страницы блока или объекта."
          }
        />
        <Pager
          total={issues.data.total}
          limit={PER_PAGE}
          offset={offset}
          path={HERE}
          params={params}
        />
      </section>
    </>
  );
}

function Summary({ stats }: { stats: IssueStats }) {
  const open =
    stats.total - (stats.by_status.closed ?? 0) - (stats.by_status.rejected ?? 0);

  return (
    <>
      {stats.open_critical > 0 && (
        <p className="bk-mismatch" role="status">
          <span aria-hidden="true">⛔</span>
          <span>
            Незакрытых критичных: {thousands(stats.open_critical)}. Пока они не решены, выпуск будет
            заблокирован.
          </span>
        </p>
      )}

      <div className="is-stats">
        <section className="stat stat--amber">
          <div className="stat__value">{thousands(stats.open_critical)}</div>
          <div className="stat__label">Критичных не закрыто</div>
        </section>
        <section className="stat stat--violet">
          <div className="stat__value">{thousands(stats.open_major)}</div>
          <div className="stat__label">Серьёзных не закрыто</div>
        </section>
        <section className="stat stat--blue">
          <div className="stat__value">{thousands(open)}</div>
          <div className="stat__label">Всего не закрыто</div>
        </section>
        <section className="stat stat--green">
          <div className="stat__value">{thousands(stats.by_status.closed ?? 0)}</div>
          <div className="stat__label">Закрыто</div>
        </section>
      </div>
    </>
  );
}

const COLUMNS: Column<IssueRow>[] = [
  {
    title: "Код",
    cell: (row) => <CopyId value={row.code} title="код ошибки" />,
  },
  {
    title: "Описание",
    cell: (row) => (
      <>
        <Link className="wk-link is-description" href={`${HERE}/${row.id}`}>
          {row.description.length > 140 ? `${row.description.slice(0, 140)}…` : row.description}
        </Link>
        <span className="tile__note">
          {row.block_code ?? row.object_code} · {row.book_title}
        </span>
      </>
    ),
  },
  {
    title: "Категория",
    secondary: true,
    cell: (row) => ISSUE_CATEGORY_LABEL[row.category],
  },
  {
    title: "Серьёзность",
    sort: "severity",
    sortFirst: "asc",
    cell: (row) => (
      <span className={ISSUE_SEVERITY_CHIP[row.severity]}>{ISSUE_SEVERITY_LABEL[row.severity]}</span>
    ),
  },
  {
    title: "Состояние",
    sort: "status",
    sortFirst: "asc",
    cell: (row) => (
      <span className={ISSUE_STATUS_CHIP[row.status]}>{ISSUE_STATUS_LABEL[row.status]}</span>
    ),
  },
  {
    title: "Вес",
    sort: "priority",
    sortFirst: "desc",
    numeric: true,
    secondary: true,
    cell: (row) => thousands(row.priority_score),
  },
  {
    title: "Заведено",
    sort: "created",
    sortFirst: "desc",
    secondary: true,
    cell: (row) => (row.detected_by ?? (row.automatic ? "проверка" : "—")) + " · " + when(row.created_at),
  },
];
