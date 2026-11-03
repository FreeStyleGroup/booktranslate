import type { Metadata } from "next";
import Link from "next/link";

import { load, type Document, type Project } from "../../lib/work";
import { FORMAT_LABEL, fileSize, when } from "../labels";
import "../work.css";
import { DocumentList } from "./doc-list";

export const metadata: Metadata = {
  title: "Исходные файлы — BookTranslate",
  description: "Файлы, загруженные в книги и проекты.",
};

/* Исходные файлы рабочего пространства.

   Файл — то, что принесли для перевода, а переводят книгу: загружают его на её
   странице, там же видно, какую роль он играет. Здесь только общий список: найти «тот
   самый docx» и убрать лишнее. */

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default async function DocumentsPage({
  searchParams,
}: {
  searchParams: Promise<{ project?: string }>;
}) {
  const { project } = await searchParams;
  // Значение из адреса уходит в запрос к API. Непроверенное, оно
  // подставило бы в путь что угодно; прав это не добавляет, но и
  // отправлять туда мусор незачем.
  const chosen = project !== undefined && UUID.test(project) ? project : undefined;

  const projects = await load<Project[]>("/projects?limit=200", "/app/documents");
  const documents = await load<Document[]>(
    chosen === undefined ? "/documents?limit=200" : `/documents?limit=200&project_id=${chosen}`,
    "/app/documents",
  );

  if (projects.error !== undefined || documents.error !== undefined) {
    return (
      <section className="tile">
        <h2>Исходные файлы</h2>
        <p className="tile__empty">{projects.error ?? documents.error}</p>
      </section>
    );
  }

  const names = new Map(projects.data.map((item) => [item.id, item.name]));

  return (
    <>
      <header className="wk-head">
        <div>
          <h1>Исходные файлы</h1>
          <p className="tile__note">
            Всё, что загружено в книги. Новый файл добавляется на странице книги.
          </p>
        </div>
      </header>

      {projects.data.length > 1 && (
        <nav className="wk-filter" aria-label="Отбор по проекту">
          <Link className={chosen === undefined ? "is-active" : ""} href="/app/documents">
            Все проекты
          </Link>
          {projects.data.map((item) => (
            <Link
              key={item.id}
              className={chosen === item.id ? "is-active" : ""}
              href={`/app/documents?project=${item.id}`}
            >
              {item.name}
            </Link>
          ))}
        </nav>
      )}

      {documents.data.length === 0 ? (
        <section className="tile wk-empty">
          <span aria-hidden="true">📕</span>
          <h2>Файлов пока нет</h2>
          <p>Заведите книгу и загрузите её текст: файл появится и здесь.</p>
          <Link className="btn btn--primary" href="/app/books">
            К книгам
          </Link>
        </section>
      ) : (
        /* Подписи строк собираются здесь, а список отрисовывает клиентский
           компонент: поиск отбирает уже загруженное, и тащить в браузер
           справочник проектов ради одного названия незачем. */
        <DocumentList
          rows={documents.data.map((document) => ({
            id: document.id,
            title: document.title,
            project: names.get(document.project_id) ?? "Проект",
            about: `${names.get(document.project_id) ?? "Проект"} · ${
              FORMAT_LABEL[document.source_format] ?? document.source_format
            } · ${fileSize(document.size_bytes)}`,
            bookId: document.book_id,
            updated: when(document.updated_at),
          }))}
        />
      )}
    </>
  );
}
