import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { currentUser } from "../../../../../../lib/current-user";
import { organizationId } from "../../../../../../lib/session";
import {
  load,
  type Book,
  type BookStructure,
  type TermCandidate,
  type TerminologyGate,
} from "../../../../../../lib/work";
import "../../../../../work.css";
import "../../../../../ui/ui.css";
import "../../../../books.css";
import "../../../../../terms/terms.css";
import { decideChapterTerms, extractChapterTerms } from "../../../../../terms/actions";
import { TermsBoard } from "../../../../../terms/board";
import { Decided } from "../../../../../terms/decided";
import { ExtractButton } from "../../../../../terms/extract-button";
import { GatePanel } from "../../../../gate-panel";

export const metadata: Metadata = {
  title: "Термины главы — BookTranslate",
  description: "Кандидаты в словарь по тексту мастера главы и решения по ним.",
};

/* Кандидаты в словарь по главе.

   Проход идёт по тексту текущего мастера главы и записывается вместе с
   его версией: версия глоссария утверждается только по главам, где
   кандидаты собраны по нынешнему тексту. Слово, уже решённое в словаре
   проекта, приходит решённым — спрашивать о нём в каждой главе значит
   получить двадцать шансов назвать его по-разному. */

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// Кто собирает и решает. Тот же набор, что в API.
const EDITING = new Set(["owner", "admin", "manager", "translator"]);

export default async function ChapterTermsPage({
  params,
}: {
  params: Promise<{ id: string; chapterId: string }>;
}) {
  const { id, chapterId } = await params;

  if (!UUID.test(id) || !UUID.test(chapterId)) {
    notFound();
  }

  const chapterPath = `/app/books/${id}/chapters/${chapterId}`;
  const here = `${chapterPath}/terms`;

  const [book, structure, gate, candidates, me, organization] = await Promise.all([
    load<Book>(`/books/${id}`, here),
    load<BookStructure>(`/books/${id}/chapters`, here),
    load<TerminologyGate>(`/chapters/${chapterId}/terminology/gate`, here),
    load<TermCandidate[]>(`/chapters/${chapterId}/terminology?limit=1000`, here),
    currentUser(here),
    organizationId(),
  ]);

  const chapter = structure.data?.chapters.find((item) => item.id === chapterId);

  if (
    book.error !== undefined ||
    gate.error !== undefined ||
    candidates.error !== undefined ||
    chapter === undefined
  ) {
    return (
      <section className="tile">
        <h2>Термины главы</h2>
        <p className="tile__empty">
          {book.error ?? gate.error ?? candidates.error ?? "Глава не найдена"}
        </p>
        <div className="tile__foot">
          <Link className="btn btn--ghost btn--small" href={chapterPath}>
            К главе
          </Link>
        </div>
      </section>
    );
  }

  const membership =
    me?.memberships.find((item) => item.organization_id === organization) ?? me?.memberships[0];
  const canEdit = membership !== undefined && EDITING.has(membership.role);

  const decided = candidates.data.filter((item) => item.status !== "new");
  const started = gate.data.current_pass !== null || candidates.data.length > 0;

  return (
    <>
      <div className="tm-head">
        <div>
          <p className="wk-crumbs">
            <Link href="/app/books">Книги</Link>
            <span aria-hidden="true"> · </span>
            <Link href={`/app/books/${id}`}>{book.data.title}</Link>
            <span aria-hidden="true"> · </span>
            <Link href={`/app/books/${id}/terminology`}>Терминология</Link>
          </p>
          <h2>Термины главы</h2>
          <p className="tile__note">
            <Link href={chapterPath}>
              {[chapter.code, chapter.title ?? `глава ${chapter.ordinal}`]
                .filter((part) => part !== null)
                .join(" · ")}
            </Link>
          </p>
        </div>

        {canEdit && gate.data.master_id !== null && (
          <ExtractButton
            extract={extractChapterTerms.bind(null, id, chapterId)}
            again={gate.data.collected}
          />
        )}
      </div>

      <GatePanel gate={gate.data} bookId={id} termsLink={false} />

      {gate.data.master_id === null ? (
        <section className="tile wk-call">
          <h3>Текста главы ещё нет</h3>
          <p>
            Термины собираются по мастеру главы — неизменяемому снимку её текста.{" "}
            <Link href={chapterPath}>Извлеките мастер</Link>, и здесь можно будет пройти по нему.
          </p>
        </section>
      ) : !started ? (
        <section className="tile wk-call">
          <h3>Проход по главе ещё не делался</h3>
          <p>
            Программа пройдёт по тексту главы и соберёт то, что в нём повторяется: термины,
            аббревиатуры, обозначения. Листинги в проход не идут — код не переводится. Уже решённое
            в словаре проекта придёт решённым.
          </p>
        </section>
      ) : canEdit ? (
        <TermsBoard
          storageKey={`bt-terms-chapter-${chapterId}`}
          candidates={candidates.data}
          decide={decideChapterTerms.bind(null, id, chapterId)}
          done={
            <>
              По этой главе решать больше нечего. Дальше — собрать и утвердить версию глоссария на
              экране <Link href={`/app/books/${id}/terminology`}>«Терминология»</Link>.
            </>
          }
        />
      ) : (
        <p className="tile__note">
          Решать кандидатов может переводчик, менеджер или администратор.
        </p>
      )}

      {decided.length > 0 && <Decided candidates={decided} />}
    </>
  );
}
