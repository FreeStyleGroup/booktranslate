import type { Metadata } from "next";
import Link from "next/link";

import {
  load,
  type Book,
  type BookPage,
  type BookSort,
  type Project,
  type SortOrder,
} from "../../lib/work";
import { BOOK_STATUS_CHIP, BOOK_STATUS_LABEL, plural, thousands, when } from "../labels";
import "../work.css";
import "../ui/ui.css";
import { CopyId } from "../ui/copy-id";
import { Pager } from "../ui/pager";
import { oneOf, paramsOf, wholeNumber } from "../ui/query";
import { DataTable, type Column } from "../ui/table";
import { NewBook } from "./new-book";

export const metadata: Metadata = {
  title: "Книги — BookTranslate",
  description: "Издания: комплект исходников, главы и выпуски.",
};

/* Книги.

   Книга — не файл. У неё несколько источников с разными ролями: из
   основного берут текст, по визуальному эталону сверяют вёрстку,
   вспомогательные лежат рядом. Поэтому список книг и список загруженных
   файлов — разные экраны: здесь видно, что переводится, а в документах —
   что принесли.

   Порядок, страница и отбор живут в адресе: так список остаётся ссылкой,
   а упорядочить его можно по-настоящему — запросом, а не внутри выданных
   пятидесяти строк. */

const HERE = "/app/books";

// Сколько книг на странице. Пятьдесят — столько влезает в экран прокруткой
// без того, чтобы страница стала бесконечной.
const PER_PAGE = 50;

// Больше этого смещение не бывает ни у одного заказчика; предел стоит,
// чтобы подобранное в адресе число не уходило в запрос как есть.
const OFFSET_MAX = 100000;

// Значения типизованы теми же наборами, что принимает API: опечатка в
// любом из них тогда не доедет до запроса, а остановится на сборке.
const SORTS: readonly BookSort[] = ["code", "title", "updated"];
const ORDERS: readonly SortOrder[] = ["asc", "desc"];

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

type Row = Book & { project: string };

export default async function BooksPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = paramsOf(await searchParams);

  const project = params.get("project");
  const chosen = project !== null && UUID.test(project) ? project : undefined;
  const sort = oneOf(params.get("sort"), SORTS, "code");
  const order = oneOf(params.get("order"), ORDERS, "desc");
  const offset = wholeNumber(params.get("offset"), 0, OFFSET_MAX);

  const query = `sort=${sort}&order=${order}&limit=${PER_PAGE}&offset=${offset}`;
  const [projects, books] = await Promise.all([
    load<Project[]>("/projects?limit=200", HERE),
    load<BookPage>(
      chosen === undefined ? `/books?${query}` : `/projects/${chosen}/books?${query}`,
      HERE,
    ),
  ]);

  if (projects.error !== undefined || books.error !== undefined) {
    return (
      <section className="tile">
        <h2>Книги</h2>
        <p className="tile__empty">{projects.error ?? books.error}</p>
      </section>
    );
  }

  const names = new Map(projects.data.map((item) => [item.id, item.name]));
  const rows: Row[] = books.data.items.map((book) => ({
    ...book,
    project: names.get(book.project_id) ?? "Проект",
  }));

  return (
    <>
      <NewBook projects={projects.data} current={chosen}>
        <div>
          <h1>Книги</h1>
          <p className="tile__note">
            Издание и комплект его исходников: основной текст, визуальный эталон, приложения.
          </p>
        </div>
      </NewBook>

      {projects.data.length === 0 && (
        <section className="tile wk-empty">
          <span aria-hidden="true">🗃</span>
          <h2>Сначала нужен проект</h2>
          <p>
            Книга заводится в проекте — он задаёт языковую пару и словарь, по которым её будут
            переводить.
          </p>
          <Link className="btn btn--primary" href="/app/projects">
            К проектам
          </Link>
        </section>
      )}

      {projects.data.length > 1 && (
        <nav className="wk-filter" aria-label="Отбор по проекту">
          {/* Отбор меняет список, поэтому сбрасывает и страницу: иначе
              выбранный проект открылся бы со второй страницы чужого
              списка и показался бы пустым. */}
          <Link className={chosen === undefined ? "is-active" : ""} href={HERE}>
            Все проекты
          </Link>
          {projects.data.map((item) => (
            <Link
              key={item.id}
              className={chosen === item.id ? "is-active" : ""}
              href={`${HERE}?project=${item.id}`}
            >
              {item.name}
            </Link>
          ))}
        </nav>
      )}

      {projects.data.length > 0 && (
        <section className="tile">
          <div className="tile__head">
            <h3>Издания</h3>
            {books.data.total > 0 && <span className="tile__note">{counted(books.data.total)}</span>}
          </div>

          <DataTable
            caption="Издания книг"
            columns={columns(chosen === undefined && projects.data.length > 1)}
            rows={rows}
            sort={{ by: sort, descending: order === "desc", path: HERE, params }}
            empty={
              // Пустая страница при непустом списке — это промах в адресе,
              // а не отсутствие работы, и говорить о них одно и то же
              // значит направить человека не туда.
              offset > 0 ? (
                <>На этой странице книг нет — вернитесь к началу списка.</>
              ) : (
                <>
                  Книг пока нет. Книга — это рамка вокруг исходников: заведите её, и в неё можно
                  будет включить EPUB основным текстом, а PDF — визуальным эталоном.
                </>
              )
            }
          />

          <Pager
            total={books.data.total}
            limit={books.data.limit}
            offset={books.data.offset}
            path={HERE}
            params={params}
          />
        </section>
      )}
    </>
  );
}

/** Столбцы списка. Столбец проекта — только когда проектов показано
 *  несколько: при отборе по одному он повторял бы выбранное в каждой
 *  строке. */
function columns(withProject: boolean): Column<Row>[] {
  const all: (Column<Row> | null)[] = [
    {
      title: "Код",
      // Сервер упорядочивает по номеру издания, а не по строке кода: иначе
      // после сотой книги «BK100» встало бы раньше «BK99».
      sort: "code",
      sortFirst: "desc",
      // Код копируется нажатием: по нему книгу называют в переписке и в
      // номерах замечаний, и набирать его руками — значит однажды
      // перепутать цифру.
      cell: (row) => <CopyId value={row.code} title="код книги" />,
    },
    {
      title: "Название",
      sort: "title",
      cell: (row) => (
        <Link className="wk-link" href={`${HERE}/${row.id}`}>
          <b>{row.title}</b>
          {row.author !== null && <span className="tile__note"> · {row.author}</span>}
        </Link>
      ),
    },
    withProject ? { title: "Проект", secondary: true, cell: (row) => row.project } : null,
    {
      title: "Пара",
      secondary: true,
      cell: (row) => (
        <span className="chip chip--info">
          {row.source_language} → {row.target_language}
        </span>
      ),
    },
    {
      title: "Состояние",
      cell: (row) => (
        <span className={BOOK_STATUS_CHIP[row.status] ?? "chip chip--info"}>
          {BOOK_STATUS_LABEL[row.status] ?? row.status}
        </span>
      ),
    },
    {
      title: "Обновлена",
      sort: "updated",
      sortFirst: "desc",
      secondary: true,
      cell: (row) => <span className="tile__note">{when(row.updated_at)}</span>,
    },
  ];

  return all.filter((column): column is Column<Row> => column !== null);
}

function counted(total: number): string {
  return `${thousands(total)} ${plural(total, "книга", "книги", "книг")}`;
}
