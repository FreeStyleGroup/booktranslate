import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { currentUser } from "../../../../../../../lib/current-user";
import { organizationId } from "../../../../../../../lib/session";
import {
  load,
  type Book,
  type BookStructure,
  type RevisionChange,
  type RevisionHistory,
} from "../../../../../../../lib/work";
import {
  REVISION_ORIGIN_CHIP,
  REVISION_ORIGIN_LABEL,
  REVISION_STAGE_LABEL,
  when,
} from "../../../../../../labels";
import "../../../../../../work.css";
import "../../../../../../ui/ui.css";
import "../../../../../books.css";
import { CopyId } from "../../../../../../ui/copy-id";
import { AdoptButton, RetranslateButton } from "./revision-actions";

export const metadata: Metadata = {
  title: "История редакций блока — BookTranslate",
  description: "Все редакции перевода блока: откуда взялись и чем отличаются.",
};

/* История редакций блока.

   Новые сверху, у каждой — откуда она: модель, версия промпта, глоссарий.
   «Перевести заново» создаёт вариант, а не заменяет текст: он появляется
   рядом с текущей редакцией со сравнением, и становится текущим, только
   если человек его примет. Прежний текст остаётся здесь в любом случае. */

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// Те же наборы, что в API: кнопку показывать тому, кто ею может воспользоваться.
const TRANSLATING = new Set(["owner", "admin", "manager", "translator"]);
const EDITING = new Set(["owner", "admin", "manager", "translator", "reviewer"]);

function Changes({ items }: { items: RevisionChange[] }) {
  return (
    <p className="bk-diff">
      {items.map((item, index) =>
        item.op === "insert" ? (
          <ins key={index}>{item.text}</ins>
        ) : item.op === "delete" ? (
          <del key={index}>{item.text}</del>
        ) : (
          <span key={index}>{item.text}</span>
        ),
      )}
    </p>
  );
}

export default async function BlockHistoryPage({
  params,
}: {
  params: Promise<{ id: string; chapterId: string; blockId: string }>;
}) {
  const { id, chapterId, blockId } = await params;

  if (!UUID.test(id) || !UUID.test(chapterId) || !UUID.test(blockId)) {
    notFound();
  }

  const chapterPath = `/app/books/${id}/chapters/${chapterId}`;
  const here = `${chapterPath}/translation/${blockId}`;

  const [book, structure, history, me, organization] = await Promise.all([
    load<Book>(`/books/${id}`, here),
    load<BookStructure>(`/books/${id}/chapters`, here),
    load<RevisionHistory>(`/blocks/${blockId}/revisions`, here),
    currentUser(here),
    organizationId(),
  ]);

  const chapter = structure.data?.chapters.find((item) => item.id === chapterId);

  if (book.error !== undefined || history.error !== undefined || chapter === undefined) {
    return (
      <section className="tile">
        <h2>История редакций</h2>
        <p className="tile__empty">{book.error ?? history.error ?? "Глава не найдена"}</p>
        <div className="tile__foot">
          <Link className="btn btn--ghost btn--small" href={`${chapterPath}/translation`}>
            К переводу главы
          </Link>
        </div>
      </section>
    );
  }

  const membership =
    me?.memberships.find((item) => item.organization_id === organization) ?? me?.memberships[0];
  const canTranslate = membership !== undefined && TRANSLATING.has(membership.role);
  const canAdopt = membership !== undefined && EDITING.has(membership.role);

  const block = history.data;
  const fullCode = chapter.code !== null ? `${chapter.code}-${block.code}` : block.code;
  const current = block.items.find((item) => item.current);

  return (
    <>
      <header className="wk-head">
        <div>
          <p className="wk-crumbs">
            <Link href="/app/books">Книги</Link>
            <span aria-hidden="true"> · </span>
            <Link href={`/app/books/${id}`}>{book.data.title}</Link>
            <span aria-hidden="true"> · </span>
            <Link href={chapterPath}>{chapter.title ?? `Глава ${chapter.ordinal}`}</Link>
            <span aria-hidden="true"> · </span>
            <Link href={`${chapterPath}/translation#${block.code}`}>Перевод</Link>
          </p>
          <h1>История редакций</h1>
        </div>

        <div className="bk-head__side">
          <CopyId value={fullCode} title="код блока" />
          {!block.active && <span className="chip chip--warn">выведен из мастера</span>}
        </div>
      </header>

      <section className="tile">
        <div className="tile__head">
          <h3>Исходник</h3>
          {canTranslate && block.active && !block.protected && (
            <RetranslateButton
              bookId={id}
              chapterId={chapterId}
              blockId={block.block_id}
              baseRevisionId={current?.id ?? null}
            />
          )}
        </div>
        <p className="bk-block-text">{block.source_text}</p>
      </section>

      {block.items.length === 0 ? (
        <section className="tile">
          <p className="tile__empty">Этот блок ещё не переводили.</p>
        </section>
      ) : (
        block.items.map((revision) => (
          <section
            key={revision.id}
            className={revision.current ? "tile bk-revision is-current" : "tile bk-revision"}
          >
            <div className="tile__head">
              <h3>Редакция {revision.revision_no}</h3>
              <span className="bk-block-id">
                <span className={REVISION_ORIGIN_CHIP[revision.origin] ?? "chip chip--info"}>
                  {REVISION_ORIGIN_LABEL[revision.origin] ?? revision.origin}
                </span>
                <span className="chip chip--info">
                  {REVISION_STAGE_LABEL[revision.stage] ?? revision.stage}
                </span>
                {revision.current ? (
                  <span className="chip chip--ok">текущая</span>
                ) : (
                  <span className="chip chip--warn">не текущая</span>
                )}
              </span>
            </div>

            <p className="bk-block-text">{revision.text}</p>

            {revision.changes.length > 0 && (
              <details className="bk-raw" open={!revision.current}>
                <summary>Что изменилось относительно редакции {revision.compared_with}</summary>
                <Changes items={revision.changes} />
              </details>
            )}

            <p className="tile__note">
              {[
                when(revision.created_at),
                revision.model !== null ? `модель ${revision.model}` : null,
                revision.prompt_version !== null ? `промпт ${revision.prompt_version}` : null,
                revision.glossary_label !== null
                  ? `глоссарий ${revision.glossary_label}`
                  : revision.run_id !== null
                    ? "без утверждённого глоссария"
                    : null,
                revision.copied_from_id !== null ? "взят перевод того же текста из книги" : null,
                revision.memory_unit_id !== null ? "взят из памяти переводов" : null,
                revision.ignore_terminology ? "в обход гейта терминологии" : null,
                revision.author,
              ]
                .filter((part) => part !== null)
                .join(" · ")}
            </p>

            {canAdopt &&
              block.active &&
              !revision.current &&
              revision.supersedes_id === (current?.id ?? null) && (
                <div className="wk-actions">
                  <AdoptButton
                    bookId={id}
                    chapterId={chapterId}
                    blockId={block.block_id}
                    revisionId={revision.id}
                  />
                </div>
              )}
          </section>
        ))
      )}
    </>
  );
}
