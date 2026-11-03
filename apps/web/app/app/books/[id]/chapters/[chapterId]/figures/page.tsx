import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { currentUser } from "../../../../../../lib/current-user";
import { organizationId } from "../../../../../../lib/session";
import { load, type ChapterFigures } from "../../../../../../lib/work";
import { plural, thousands } from "../../../../../labels";
import "../../../../../work.css";
import "../../../../../ui/ui.css";
import "../../../../books.css";
import "../../../../../issues/issues.css";
import { FigureCard, FiguresHead } from "./figure-card";

export const metadata: Metadata = {
  title: "Рисунки главы — BookTranslate",
  description: "Перевод надписей на рисунках: оригинал рядом с переводом и решение по каждому.",
};

/* Рисунки главы.

   Сверка всегда рядом с оригиналом. Оригинал не меняется, перевод — отдельный файл, а решение по
   картинке нужно всегда: утвердить, оставить как в книге или подтвердить, что надписей нет. */

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// Те же наборы, что в API.
const WORKING = new Set(["owner", "admin", "manager", "translator"]);
const DECIDING = new Set(["owner", "admin", "manager", "reviewer"]);

export default async function FiguresPage({
  params,
}: {
  params: Promise<{ id: string; chapterId: string }>;
}) {
  const { id, chapterId } = await params;

  if (!UUID.test(id) || !UUID.test(chapterId)) {
    notFound();
  }

  const chapterHref = `/app/books/${id}/chapters/${chapterId}`;
  const here = `${chapterHref}/figures`;

  const [figures, me, organization] = await Promise.all([
    load<ChapterFigures>(`/chapters/${chapterId}/figures`, here),
    currentUser(here),
    organizationId(),
  ]);

  if (figures.error !== undefined) {
    return (
      <section className="tile">
        <h2>Рисунки главы</h2>
        <p className="tile__empty">{figures.error}</p>
        <div className="tile__foot">
          <Link className="btn btn--ghost btn--small" href={chapterHref}>
            К главе
          </Link>
        </div>
      </section>
    );
  }

  const membership =
    me?.memberships.find((item) => item.organization_id === organization) ?? me?.memberships[0];
  const role = membership?.role ?? "viewer";
  const canWork = WORKING.has(role);
  const canDecide = DECIDING.has(role);

  return (
    <>
      <header className="wk-head">
        <div>
          <p className="wk-crumbs">
            <Link href="/app/books">Книги</Link>
            <span aria-hidden="true"> · </span>
            <Link href={chapterHref}>Глава</Link>
          </p>
          <h1>Рисунки главы</h1>
          <p className="tile__note">
            {thousands(figures.data.images.length)}{" "}
            {plural(figures.data.images.length, "рисунок", "рисунка", "рисунков")}, без решения:{" "}
            {thousands(figures.data.undecided)}
          </p>
        </div>
      </header>

      <FiguresHead
        bookId={id}
        chapterId={chapterId}
        state={figures.data}
        canWork={canWork}
      />

      {figures.data.images.map((image) => (
        <FigureCard
          key={`${image.object_id}-${image.index}-${image.current?.id ?? "new"}`}
          bookId={id}
          chapterId={chapterId}
          image={image}
          canWork={canWork}
          canDecide={canDecide}
        />
      ))}
    </>
  );
}
