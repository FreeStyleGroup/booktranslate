import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { currentUser } from "../../../lib/current-user";
import { organizationId } from "../../../lib/session";
import {
  load,
  type Book,
  type BookKit,
  type BookStructure,
  type Document,
  type Project,
} from "../../../lib/work";
import { BOOK_STATUS_CHIP, BOOK_STATUS_LABEL, plural, thousands, when } from "../../labels";
import "../../work.css";
import "../../ui/ui.css";
import "../books.css";
import { CopyId } from "../../ui/copy-id";
import { AddSource } from "../add-source";
import { Kit } from "../kit";

export const metadata: Metadata = {
  title: "Книга — BookTranslate",
  description: "Комплект исходников книги: роли, контрольные суммы, проверка файлов.",
};

/* Карточка книги: комплект исходников.

   Книга — рамка вокруг исходников, а не файл. Из основного источника
   берут текст, по визуальному эталону сверяют вёрстку, вспомогательные
   лежат рядом. Поэтому главное на этом экране — состав комплекта и то,
   годится ли каждый файл: проверить это надо до начала работы, а не через
   час на пустом разборе.

   Главы, блоки и перевод появятся здесь дальше по конвейеру. Пока их нет,
   экран об этом говорит прямо, а не делает вид, что книга готова к
   работе. */

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// Кто собирает комплект. Тот же набор, что в API: владелец вправе всё в
// своей организации и в списке не перечисляется.
const MANAGING = new Set(["owner", "admin", "manager", "translator"]);

export default async function BookPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  if (!UUID.test(id)) {
    notFound();
  }

  const here = `/app/books/${id}`;
  const book = await load<Book>(`/books/${id}`, here);

  if (book.error !== undefined) {
    return (
      <section className="tile">
        <h2>Книга</h2>
        <p className="tile__empty">{book.error}</p>
        <div className="tile__foot">
          <Link className="btn btn--ghost btn--small" href="/app/books">
            К списку книг
          </Link>
        </div>
      </section>
    );
  }

  const edition = book.data;
  const [kit, project, documents, me, organization, structure] = await Promise.all([
    load<BookKit>(`/books/${id}/sources`, here),
    load<Project>(`/projects/${edition.project_id}`, here),
    // Файлы проекта, чтобы предложить уже загруженные. Потолок тот же, что
    // на списке документов: отбор по «ни в одной книге» в API пока не
    // заведён, и просить его ради одного раскрывающегося списка рано.
    load<Document[]>(`/documents?project_id=${edition.project_id}&limit=200`, here),
    currentUser(here),
    organizationId(),
    load<BookStructure>(`/books/${id}/chapters`, here),
  ]);

  const membership =
    me?.memberships.find((item) => item.organization_id === organization) ?? me?.memberships[0];
  const canManage = membership !== undefined && MANAGING.has(membership.role);

  const free = (documents.data ?? []).filter((document) => document.book_id === null);
  const hasPrimary = (kit.data?.sources ?? []).some(
    (source) => source.source_role === "primary_text",
  );

  return (
    <>
      <header className="wk-head">
        <div>
          <p className="wk-crumbs">
            <Link href="/app/books">Книги</Link>
            {project.data !== undefined && (
              <>
                <span aria-hidden="true"> · </span>
                <Link href={`/app/books?project=${edition.project_id}`}>{project.data.name}</Link>
              </>
            )}
          </p>

          <h1>{edition.title}</h1>

          <p className="tile__note">
            {edition.author ?? "автор не указан"}
            {edition.edition_label !== null && ` · ${edition.edition_label}`} · заведена{" "}
            {when(edition.created_at)}
          </p>
        </div>

        <div className="bk-head__side">
          {/* Код — первым делом и копируемый: по нему книгу называют в
              переписке, и он же стоит в номерах её замечаний. */}
          <CopyId value={edition.code} title="код книги" />

          <span className="chip chip--info">
            {edition.source_language} → {edition.target_language}
          </span>

          <span className={BOOK_STATUS_CHIP[edition.status] ?? "chip chip--info"}>
            {BOOK_STATUS_LABEL[edition.status] ?? edition.status}
          </span>
        </div>
      </header>

      {kit.error !== undefined ? (
        <section className="tile">
          <h2>Комплект исходников</h2>
          <p className="tile__empty">{kit.error}</p>
        </section>
      ) : (
        <>
          {/* Предупреждение о разных изданиях — над составом, а не внутри
              строки: оно про комплект целиком, а не про отдельный файл. */}
          {kit.data.mismatch !== null && (
            <p className="bk-mismatch" role="status">
              <span aria-hidden="true">⚠</span>
              <span>{kit.data.mismatch}</span>
            </p>
          )}

          <section className="tile">
            <div className="tile__head">
              <h3>Комплект исходников</h3>
              <span className="tile__note">
                {kit.data.sources.length === 0
                  ? "пока пусто"
                  : `${thousands(kit.data.sources.length)} ${plural(
                      kit.data.sources.length,
                      "файл",
                      "файла",
                      "файлов",
                    )}`}
              </span>
            </div>

            {kit.data.sources.length === 0 ? (
              <p className="tile__empty">
                Файлов в комплекте нет. Основной источник текста у книги один — из него берут
                текст; PDF рядом с ним кладут визуальным эталоном, по нему сверяют вёрстку.
              </p>
            ) : (
              <Kit bookId={edition.id} sources={kit.data.sources} canManage={canManage} />
            )}
          </section>

          {canManage && (
            <AddSource
              // Ключ по наличию основного источника: роль по умолчанию
              // зависит от него, а состояние формы после обновления
              // страницы иначе осталось бы прежним — и предлагало бы
              // занятую роль.
              key={hasPrimary ? "with-primary" : "without-primary"}
              bookId={edition.id}
              projectId={edition.project_id}
              free={free}
              hasPrimary={hasPrimary}
            />
          )}
        </>
      )}

      {/* Следующий шаг конвейера — границы глав. Плитка говорит, в каком
          он состоянии, а не просто ведёт на экран: «глав нет» и «12 из 12
          утверждены» — разные причины туда идти. */}
      <section className="tile wk-call bk-next">
        <div>
          <h3>Структура книги</h3>
          <p className="tile__note">{structureNote(structure.data)}</p>
        </div>

        <Link className="btn btn--ghost btn--small" href={`/app/books/${edition.id}/structure`}>
          Открыть
        </Link>
      </section>
    </>
  );
}

/** Состояние разметки глав одной фразой — для плитки на карточке книги. */
function structureNote(structure: BookStructure | undefined): string {
  if (structure === undefined) {
    return "Состояние глав сейчас не узнать — откройте экран структуры.";
  }

  const total = structure.chapters.length;

  if (total === 0) {
    return "Глав пока нет. Сервис предложит их по основному источнику, вы проверите и утвердите границы — только после этого глава идёт в работу.";
  }

  const approved = structure.chapters.filter(
    (chapter) => chapter.boundary_status === "approved",
  ).length;

  return `${thousands(total)} ${plural(total, "глава", "главы", "глав")}, утверждено ${thousands(approved)}.`;
}
