import type { Metadata } from "next";
import Link from "next/link";

import { load, type Document, type Project } from "../../lib/work";
import {
  DOCUMENT_CHIP,
  DOCUMENT_LABEL,
  GLOSSARY_KIND,
  fileSize,
  thousands,
  when,
} from "../labels";
import "../work.css";
import "./terms.css";
import { TermsBoard, type Candidate } from "./board";
import { ExtractButton } from "./extract-button";

export const metadata: Metadata = {
  title: "Термины книги — BookTranslate",
  description: "Кандидаты в словарь: что в книге повторяется и как это решено.",
};

/* Термины книги.

   Шаг между разбором и переводом, и пропустить его нельзя: пока по книге
   остаются нерешённые кандидаты, перевод не начинается. Причина записана в
   самом переводчике — слово, отданное модели на усмотрение, в сорока
   сегментах будет названо по-разному, и ловить это потом придётся тому, кто
   читал исходник.

   Экран привязан к книге, а не к пространству: термины собираются из
   конкретного текста, и «термины вообще» — это уже словарь, отдельный
   раздел. */

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// Разобранные документы: до разбора собирать термины не из чего.
const PARSED = new Set(["parsed", "translating", "review", "done"]);

export default async function TermsPage({
  searchParams,
}: {
  searchParams: Promise<{ document?: string }>;
}) {
  const { document } = await searchParams;
  const chosen = document !== undefined && UUID.test(document) ? document : undefined;

  const documents = await load<Document[]>("/documents?limit=200", "/app/terms");

  if (documents.error !== undefined) {
    return (
      <section className="tile">
        <h2>Термины книги</h2>
        <p className="tile__empty">{documents.error}</p>
      </section>
    );
  }

  const ready = documents.data.filter((item) => PARSED.has(item.status));

  return (
    <>
      <header className="wk-head">
        <div>
          <h1>Термины книги</h1>
          <p className="tile__note">
            Что в книге повторяется и как это называть. Решается один раз и до
            перевода: слово, отданное модели на усмотрение, в сорока сегментах
            будет названо по-разному.
          </p>
        </div>
      </header>

      {ready.length === 0 ? (
        <Empty documents={documents.data} />
      ) : chosen === undefined ? (
        <Picker documents={ready} />
      ) : (
        <Book id={chosen} documents={ready} />
      )}
    </>
  );
}

/** Разбирать нечего: книг нет вовсе или ни одна не разобрана. */
function Empty({ documents }: { documents: Document[] }) {
  const waiting = documents.length > 0;

  return (
    <section className="tile wk-empty">
      <span aria-hidden="true">🗂</span>
      <h2>{waiting ? "Сначала разбор" : "Сначала книга"}</h2>
      <p>
        {waiting
          ? "Термины собираются из текста, а текст появляется после разбора. Откройте книгу и нажмите «Разобрать»."
          : "Термины собираются из книги — загрузите её, и после разбора кандидаты появятся здесь."}
      </p>
      <Link className="btn btn--primary" href="/app/documents">
        К документам
      </Link>
    </section>
  );
}

/** Выбор книги: термины принадлежат тексту, а не пространству. */
function Picker({ documents }: { documents: Document[] }) {
  return (
    <section className="tile">
      <div className="tile__head">
        <h3>По какой книге</h3>
        <span className="tile__note">разобранных — {thousands(documents.length)}</span>
      </div>

      <div className="wk-list">
        {documents.map((item) => (
          <Link className="wk-row" key={item.id} href={`/app/terms?document=${item.id}`}>
            <span className="wk-row__mark" aria-hidden="true">
              📖
            </span>
            <span className="wk-row__name">
              <b>{item.title}</b>
              <span className="tile__note">{fileSize(item.size_bytes)}</span>
            </span>
            <span className={DOCUMENT_CHIP[item.status] ?? "chip chip--info"}>
              {DOCUMENT_LABEL[item.status] ?? item.status}
            </span>
            <span className="wk-row__when tile__note">{when(item.updated_at)}</span>
          </Link>
        ))}
      </div>
    </section>
  );
}

/** Кандидаты выбранной книги. */
async function Book({ id, documents }: { id: string; documents: Document[] }) {
  const here = `/app/terms?document=${id}`;
  const book = documents.find((item) => item.id === id);

  if (book === undefined) {
    return (
      <section className="tile">
        <p className="tile__empty">
          Эта книга не разобрана — собирать термины не из чего.
        </p>
        <div className="tile__foot">
          <Link className="btn btn--ghost btn--small" href="/app/terms">
            К списку книг
          </Link>
        </div>
      </section>
    );
  }

  const project = await load<Project>(`/projects/${book.project_id}`, here);
  const candidates = await load<Candidate[]>(
    `/documents/${id}/terminology?limit=1000`,
    here,
  );

  if (candidates.error !== undefined) {
    return (
      <section className="tile">
        <p className="tile__empty">{candidates.error}</p>
      </section>
    );
  }

  const decided = candidates.data.filter((item) => item.status !== "new");
  const started = candidates.data.length > 0;

  return (
    <>
      <div className="tm-head">
        <div>
          <p className="wk-crumbs">
            <Link href="/app/terms">Термины книги</Link>
            <span aria-hidden="true"> · </span>
            <Link href={`/app/documents/${book.id}`}>{book.title}</Link>
          </p>
          <h2>{book.title}</h2>
          {project.data !== undefined && (
            <p className="tile__note">
              {project.data.name} · {project.data.source_language} →{" "}
              {project.data.target_language}
            </p>
          )}
        </div>

        <ExtractButton documentId={book.id} again={started} />
      </div>

      {!started ? (
        <section className="tile wk-call">
          <h3>Проход по книге ещё не делался</h3>
          <p>
            Сейчас программа пройдёт по тексту и соберёт то, что в нём
            повторяется: термины, аббревиатуры, обозначения. Список нужно
            решить один раз — дальше он держит всю книгу и все следующие книги
            этого проекта.
          </p>
        </section>
      ) : (
        <TermsBoard documentId={book.id} candidates={candidates.data} />
      )}

      {decided.length > 0 && <Decided candidates={decided} />}
    </>
  );
}

/** Что уже решено. Показывается, чтобы видеть сделанное и не решать дважды. */
function Decided({ candidates }: { candidates: Candidate[] }) {
  const accepted = candidates.filter((item) => item.status === "accepted");
  const rejected = candidates.filter((item) => item.status === "rejected");

  return (
    <section className="tile">
      <div className="tile__head">
        <h3>Уже решено</h3>
        <span className="tile__note">
          принято {thousands(accepted.length)} · отклонено {thousands(rejected.length)}
        </span>
      </div>

      <div className="tm-done">
        {accepted.map((item) => (
          <span className="tm-chip" key={item.id}>
            <b>{item.source_term}</b>
            <i>{GLOSSARY_KIND[item.kind] ?? item.kind}</i>
          </span>
        ))}
        {rejected.map((item) => (
          <span className="tm-chip tm-chip--off" key={item.id}>
            <b>{item.source_term}</b>
            <i>не термин</i>
          </span>
        ))}
      </div>

      <p className="tile__note wk-seg__foot">
        Принятые термины лежат в словаре проекта и применяются ко всем его
        книгам. Поправить решение можно в разделе «Словарь».
      </p>
    </section>
  );
}
