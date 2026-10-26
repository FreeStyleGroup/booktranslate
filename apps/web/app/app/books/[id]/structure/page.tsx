import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { currentUser } from "../../../../lib/current-user";
import { organizationId } from "../../../../lib/session";
import { load, type Book, type BookStructure } from "../../../../lib/work";
import { FORMAT_LABEL, plural, thousands } from "../../../labels";
import "../../../work.css";
import "../../../ui/ui.css";
import "../../books.css";
import { FindBlock } from "../../find-block";
import { Structure } from "./structure";

export const metadata: Metadata = {
  title: "Структура книги — BookTranslate",
  description: "Главы книги: предложенные и утверждённые границы, разделы и состав.",
};

/* Структура книги: главы и их границы.

   До перевода каждой главы утверждаются её начало, конец и заголовки.
   Сервис предлагает главы по основному источнику — по заголовкам, файлам
   EPUB или страницам PDF, — человек проверяет, делит и сливает, а потом
   утверждает. Утверждённая глава получает постоянный код и только после
   этого идёт дальше — к извлечению мастер-текста. */

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// Кто правит структуру. Тот же набор, что в API: владелец вправе всё в
// своей организации и в списке не перечисляется.
const MANAGING = new Set(["owner", "admin", "manager", "translator"]);

export default async function StructurePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  if (!UUID.test(id)) {
    notFound();
  }

  const here = `/app/books/${id}/structure`;
  const [book, structure, me, organization] = await Promise.all([
    load<Book>(`/books/${id}`, here),
    load<BookStructure>(`/books/${id}/chapters`, here),
    currentUser(here),
    organizationId(),
  ]);

  if (book.error !== undefined || structure.error !== undefined) {
    return (
      <section className="tile">
        <h2>Структура книги</h2>
        <p className="tile__empty">{book.error ?? structure.error}</p>
        <div className="tile__foot">
          <Link className="btn btn--ghost btn--small" href="/app/books">
            К списку книг
          </Link>
        </div>
      </section>
    );
  }

  const membership =
    me?.memberships.find((item) => item.organization_id === organization) ?? me?.memberships[0];
  const canManage = membership !== undefined && MANAGING.has(membership.role);

  const { chapters, source } = structure.data;
  const approved = chapters.filter((chapter) => chapter.boundary_status === "approved").length;

  return (
    <>
      <header className="wk-head">
        <div>
          <p className="wk-crumbs">
            <Link href="/app/books">Книги</Link>
            <span aria-hidden="true"> · </span>
            <Link href={`/app/books/${id}`}>{book.data.title}</Link>
          </p>

          <h1>Структура книги</h1>

          <p className="tile__note">
            {chapters.length === 0
              ? "Глав пока нет"
              : `${thousands(chapters.length)} ${plural(chapters.length, "глава", "главы", "глав")}, утверждено ${thousands(approved)}`}
            {source !== null &&
              ` · размечено по «${source.original_filename ?? source.title}» (${
                FORMAT_LABEL[source.source_format] ?? source.source_format
              })`}
          </p>
        </div>

        {/* Блок по коду — из любой главы и с любой страницы: `CH03-B0042`. */}
        {chapters.some((chapter) => chapter.code !== null) && <FindBlock bookId={id} />}
      </header>

      {/* Основной источник сменили после разметки: номера блоков в
          границах — прежнего файла, к новому они не подходят. Сказать об
          этом надо до того, как человек утвердит чужие границы. */}
      {source !== null && !structure.data.source_is_primary && (
        <p className="bk-mismatch" role="status">
          <span aria-hidden="true">⚠</span>
          <span>
            Главы размечены по файлу, который больше не основной источник книги: их границы
            заданы по прежнему файлу и к новому не подходят.{" "}
            {structure.data.can_propose
              ? "Предложите главы заново."
              : "Утверждённые главы по новому файлу пока не переразмечаются — это придёт вместе с версиями мастер-текста."}
          </span>
        </p>
      )}

      <Structure
        bookId={id}
        structure={structure.data}
        canManage={canManage}
      />
    </>
  );
}
