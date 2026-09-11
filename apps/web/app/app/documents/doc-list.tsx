"use client";

/* Список загруженных книг с поиском.

   Поиск идёт по уже загруженному списку, а не запросом к API. Причина в
   размере: список приходит целиком (потолок — 200 книг), и гонять запрос
   на каждую букву ради отбора того, что уже лежит в браузере, значит
   сделать поиск медленнее самой прокрутки. Когда книг станет больше
   потолка, поиск переедет в API вместе с постраничной выдачей.

   Ищем по названию, имени файла и проекту: человек помнит книгу по-разному
   — «тот docx, что присылали в марте» и «справочник по API» одинаково
   законные способы её назвать. */

import Link from "next/link";
import { useMemo, useState } from "react";

import { DOCUMENT_CHIP, DOCUMENT_LABEL, plural, thousands } from "../labels";
import { DeleteButton } from "./actions-ui";

export type Row = {
  id: string;
  title: string;
  project: string;
  about: string;
  status: string;
  updated: string;
};

export function DocumentList({ rows }: { rows: Row[] }) {
  const [query, setQuery] = useState("");

  const found = useMemo(() => {
    const needle = query.trim().toLowerCase();

    if (needle === "") {
      return rows;
    }

    return rows.filter((row) =>
      `${row.title} ${row.project} ${row.about}`.toLowerCase().includes(needle),
    );
  }, [rows, query]);

  return (
    <section className="tile">
      <div className="tile__head">
        <h3>Загруженные книги</h3>

        <label className="wk-find">
          <span aria-hidden="true">🔍</span>
          <input
            type="search"
            value={query}
            placeholder="Поиск по книгам"
            aria-label="Поиск по книгам"
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
      </div>

      {found.length === 0 ? (
        <p className="tile__empty">
          Ничего не нашлось. Искали по названию, имени файла и проекту —
          попробуйте другое слово.
        </p>
      ) : (
        /* Строка и кнопка удаления — соседи, а не вложенные друг в друга:
           кнопка внутри ссылки и разметку ломает, и нажатие по ней увело бы
           на страницу книги вместо удаления. */
        <div className="wk-list">
          {found.map((row) => (
            <div className="wk-item" key={row.id}>
              <Link className="wk-row" href={`/app/documents/${row.id}`}>
                <span className="wk-row__mark" aria-hidden="true">
                  📄
                </span>

                <span className="wk-row__name">
                  <b>{row.title}</b>
                  <span className="tile__note">{row.about}</span>
                </span>

                <span className={DOCUMENT_CHIP[row.status] ?? "chip chip--info"}>
                  {DOCUMENT_LABEL[row.status] ?? row.status}
                </span>

                <span className="wk-row__when tile__note">{row.updated}</span>
              </Link>

              <DeleteButton id={row.id} title={row.title} icon />
            </div>
          ))}
        </div>
      )}

      {/* Сколько нашлось — только пока ищут: без отбора это число ничего не
          добавляет к списку, который и так виден целиком. */}
      {query.trim() !== "" && found.length > 0 && (
        <p className="tile__note wk-seg__foot">
          Нашлось {thousands(found.length)}{" "}
          {plural(found.length, "книга", "книги", "книг")} из {thousands(rows.length)}
        </p>
      )}
    </section>
  );
}
