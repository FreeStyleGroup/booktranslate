/* Таблица со сортировкой на сервере.

   Серверный компонент: строки приходят уже отобранными и упорядоченными,
   а заголовок столбца — обычная ссылка. Это не экономия на скрипте, а
   единственный честный способ: в браузере можно упорядочить только
   выданную страницу, и «по названию» означало бы «по названию среди этих
   пятидесяти».

   Таблица одна на весь кабинет, потому что дальше таких экранов будет
   много — главы, блоки, замечания, выпуски. Пять таблиц, написанных
   по месту, разъедутся в мелочах: где-то пропадёт `aria-sort`, где-то
   сортировка не сбросит номер страницы. */

import Link from "next/link";
import type { ReactNode } from "react";

import { linkTo } from "./query";

export type Column<Row> = {
  title: string;
  /** Что показать в клетке. Разметку собирает вызывающий: ему видно, где
   *  нужна ссылка, где значок состояния, а где просто число. */
  cell: (row: Row) => ReactNode;
  /** Значение `?sort=`, если по столбцу можно упорядочить. Без него
   *  заголовок остаётся текстом — и это видно глазом, а не на ощупь. */
  sort?: string;
  /** С какого направления начинать при первом нажатии. Названия — от «А»,
   *  даты и счёт — свежее и большее сверху: это то, что человек ищет,
   *  нажимая на заголовок. Задаётся явно, а не угадывается по виду
   *  столбца: дата не число, но начинается тоже с убывания. */
  sortFirst?: "asc" | "desc";
  /** Числа — по правому краю: так совпадают разряды. */
  numeric?: boolean;
  /** Столбец, который на узком экране прячется. Сворачивать таблицу в
   *  карточки ради телефона здесь нечем, а вот второстепенное убрать
   *  можно: по горизонтали экран кабинета не прокручивается. */
  secondary?: boolean;
};

export type SortState = {
  /** По какому столбцу сейчас. */
  by: string;
  /** Сверху — большее. */
  descending: boolean;
  /** Адрес страницы без параметров. */
  path: string;
  /** Параметры адреса, какими они пришли: ссылка в заголовке меняет
   *  порядок, но сохраняет отбор. */
  params: URLSearchParams;
};

export function DataTable<Row extends { id: string }>({
  caption,
  columns,
  rows,
  sort,
  empty,
  rowAnchor,
}: {
  /** Чем таблица является. Для глаз — заголовком блока, для чтения с
   *  экрана — подписью: таблица без подписи читается как «таблица». */
  caption: string;
  columns: Column<Row>[];
  rows: Row[];
  /** Порядок, если его выбирает человек. Без него таблица показывает
   *  строки в данном порядке — так у блоков главы, чей порядок задан
   *  версией мастера, а не заголовком столбца. */
  sort?: SortState;
  /** Что сказать, когда строк нет. Пустая таблица без слов выглядит
   *  поломкой, хотя чаще всего работа просто не начата. */
  empty: ReactNode;
  /** Якорь строки в адресе — чтобы ссылка вела прямо к ней, как ссылка на
   *  блок по его коду. */
  rowAnchor?: (row: Row) => string;
}) {
  if (rows.length === 0) {
    return <p className="tile__empty">{empty}</p>;
  }

  return (
    <div className="ui-table__scroll">
      <table className="ui-table">
        <caption className="ui-table__caption">{caption}</caption>

        <thead>
          <tr>
            {columns.map((column) => (
              <th
                key={column.title}
                scope="col"
                className={cellClass(column)}
                // Состояние сортировки — атрибутом, а не только стрелкой:
                // стрелку не читает ни одна программа чтения с экрана.
                aria-sort={sort === undefined ? undefined : ariaSort(column, sort)}
              >
                {column.sort === undefined || sort === undefined ? (
                  column.title
                ) : (
                  <SortLink column={column} sort={sort} />
                )}
              </th>
            ))}
          </tr>
        </thead>

        <tbody>
          {rows.map((row) => (
            <tr key={row.id} id={rowAnchor?.(row)}>
              {columns.map((column) => (
                <td key={column.title} className={cellClass(column)}>
                  {column.cell(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SortLink<Row>({ column, sort }: { column: Column<Row>; sort: SortState }) {
  const active = column.sort === sort.by;
  // Нажатие по текущему столбцу переворачивает порядок, по другому —
  // ставит направление, с которого этот столбец принято начинать.
  const descending = active ? !sort.descending : column.sortFirst === "desc";

  return (
    <Link
      className={active ? "ui-sort is-active" : "ui-sort"}
      href={linkTo(sort.path, sort.params, {
        sort: column.sort ?? null,
        order: descending ? "desc" : "asc",
        // Смена порядка возвращает к началу: иначе человек, нажавший
        // «по названию» на третьей странице, попал бы на третью страницу
        // другого списка и решил бы, что книги пропали.
        offset: null,
      })}
    >
      {column.title}
      <span className="ui-sort__mark" aria-hidden="true">
        {active ? (sort.descending ? "↓" : "↑") : "↕"}
      </span>
    </Link>
  );
}

/* «none» означает «сортировать можно, но сейчас не отсортировано» — на
   обычном столбце это неправда, поэтому там атрибута нет вовсе. */
function ariaSort<Row>(
  column: Column<Row>,
  sort: SortState,
): "ascending" | "descending" | "none" | undefined {
  if (column.sort === undefined) {
    return undefined;
  }

  if (column.sort !== sort.by) {
    return "none";
  }

  return sort.descending ? "descending" : "ascending";
}

function cellClass<Row>(column: Column<Row>): string | undefined {
  const names = [column.numeric === true && "is-num", column.secondary === true && "is-second"]
    .filter((name) => name !== false)
    .join(" ");

  return names === "" ? undefined : names;
}
