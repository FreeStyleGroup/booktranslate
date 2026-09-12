import type { Metadata } from "next";
import Link from "next/link";

import {
  load,
  type Document,
  type Project,
  type ReviewProgress,
  type SegmentPage,
} from "../../lib/work";
import { CHECK_LABEL, DOCUMENT_CHIP, DOCUMENT_LABEL, fileSize, plural, thousands, when } from "../labels";
import "../work.css";
import "./queue.css";
import { ApproveClean, QueueBoard } from "./board";

export const metadata: Metadata = {
  title: "Очередь замечаний — BookTranslate",
  description: "Сегменты, к которым у проверок есть вопросы, начиная с худших.",
};

/* Очередь замечаний.

   Главный экран работы. Проверки при переводе отметили места, где числа,
   термины или подстановки разошлись с исходником; здесь они собраны в
   список, и разбирается он сверху вниз — от худшего.

   Очередь показывается всегда с начала, без листания по страницам. Это не
   упрощение: правка меняет оценку сегмента и его место в порядке, а
   принятое уходит из отбора совсем, поэтому «страница 2» после десятка
   правок показала бы не то, что на ней было. Очередь — это её начало, и
   разобранное само уступает место следующему. */

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// Книги, у которых вообще может быть очередь: перевод либо идёт, либо был.
const TRANSLATED = new Set(["translating", "review", "done"]);

// Сколько сегментов держать на экране. Полсотни — это уже долгая работа за
// один присест, а больше делает страницу неподъёмной: у каждой строки поле
// правки, исходник и разбор находок.
const BATCH = 50;

// Виды находок в том порядке, в каком их стоит разбирать: сначала то, где
// потеряно значение, потом расхождения со словарём. Порядок задан списком,
// а не сортировкой по числу: он не должен прыгать от книги к книге.
const CHECKS = ["empty", "untranslated", "numbers", "placeholders", "glossary", "first_use"];

export default async function QueuePage({
  searchParams,
}: {
  searchParams: Promise<{ document?: string; check?: string }>;
}) {
  const { document, check } = await searchParams;
  const chosen = document !== undefined && UUID.test(document) ? document : undefined;
  const kind = check !== undefined && CHECKS.includes(check) ? check : undefined;

  const documents = await load<Document[]>("/documents?limit=200", "/app/queue");

  if (documents.error !== undefined) {
    return (
      <section className="tile">
        <h2>Очередь замечаний</h2>
        <p className="tile__empty">{documents.error}</p>
      </section>
    );
  }

  const ready = documents.data.filter((item) => TRANSLATED.has(item.status));

  return (
    <>
      <header className="wk-head">
        <div>
          <h1>Очередь замечаний</h1>
          <p className="tile__note">
            Места, где проверки нашли расхождение с исходником: числа,
            термины, подстановки. Это не приговор переводу, а список того, на
            что стоит посмотреть глазами.
          </p>
        </div>
      </header>

      {ready.length === 0 ? (
        <Empty documents={documents.data} />
      ) : chosen === undefined ? (
        <Picker documents={ready} />
      ) : (
        <Book id={chosen} documents={ready} check={kind} />
      )}
    </>
  );
}

/** Разбирать нечего: книг нет вовсе или ни одна не переведена. */
function Empty({ documents }: { documents: Document[] }) {
  const waiting = documents.length > 0;

  return (
    <section className="tile wk-empty">
      <span aria-hidden="true">🧪</span>
      <h2>{waiting ? "Сначала перевод" : "Сначала книга"}</h2>
      <p>
        {waiting
          ? "Замечания появляются при переводе: проверки сверяют перевод с исходником и отмечают расхождения. Переведите книгу, и то, что не сошлось, соберётся здесь."
          : "Замечания собираются из переведённой книги — загрузите её, разберите и переведите."}
      </p>
      <Link className="btn btn--primary" href="/app/documents">
        К документам
      </Link>
    </section>
  );
}

/** Выбор книги: замечания принадлежат тексту, а не пространству. */
function Picker({ documents }: { documents: Document[] }) {
  return (
    <section className="tile">
      <div className="tile__head">
        <h3>По какой книге</h3>
        <span className="tile__note">переведённых — {thousands(documents.length)}</span>
      </div>

      <div className="wk-list">
        {documents.map((item) => (
          <Link className="wk-row" key={item.id} href={`/app/queue?document=${item.id}`}>
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

/** Очередь выбранной книги. */
async function Book({
  id,
  documents,
  check,
}: {
  id: string;
  documents: Document[];
  check?: string;
}) {
  const here = `/app/queue?document=${id}`;
  const book = documents.find((item) => item.id === id);

  if (book === undefined) {
    return (
      <section className="tile">
        <p className="tile__empty">Эта книга ещё не переведена — замечаний по ней нет.</p>
        <div className="tile__foot">
          <Link className="btn btn--ghost btn--small" href="/app/queue">
            К списку книг
          </Link>
        </div>
      </section>
    );
  }

  const project = await load<Project>(`/projects/${book.project_id}`, here);
  const progress = await load<ReviewProgress>(`/documents/${id}/progress`, here);
  const queue = await load<SegmentPage>(
    `/documents/${id}/segments?status=flagged&worst_first=true&limit=${BATCH}` +
      (check === undefined ? "" : `&check=${check}`),
    here,
  );

  if (progress.error !== undefined || queue.error !== undefined) {
    return (
      <section className="tile">
        <p className="tile__empty">{progress.error ?? queue.error}</p>
      </section>
    );
  }

  const state = progress.data;
  // Переведённое, к чему у проверок нет претензий и что ещё не принято.
  // Помеченное и принятое вычитаются: первое остаётся редактору, второе
  // уже закрыто.
  const clean = Math.max(0, state.translated - state.flagged - state.approved);

  return (
    <>
      <div className="qu-head">
        <div>
          <p className="wk-crumbs">
            <Link href="/app/queue">Очередь замечаний</Link>
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

        <ApproveClean documentId={book.id} clean={clean} />
      </div>

      <State state={state} />

      {state.flagged > 0 && <Filters documentId={book.id} state={state} check={check} />}

      {queue.data.items.length === 0 ? (
        <Nothing state={state} book={book} check={check} />
      ) : (
        <>
          <p className="tile__note qu-lead">
            {plural(queue.data.items.length, "Показан", "Показаны", "Показано")}{" "}
            {thousands(queue.data.items.length)} из {thousands(queue.data.total)}{" "}
            {plural(queue.data.total, "сегмента", "сегментов", "сегментов")}, начиная с
            худшего. Разобранное уходит из очереди, и на его место поднимается
            следующее — поэтому страниц здесь нет.
          </p>

          <QueueBoard segments={queue.data.items} />
        </>
      )}
    </>
  );
}

/** Полоса выполнения по книге: сколько принято, сколько ждёт. */
function State({ state }: { state: ReviewProgress }) {
  const percent = state.total === 0 ? 0 : Math.round((state.approved * 100) / state.total);

  return (
    <section className="tile qu-state">
      <div className="tr-bar">
        <div className="bar">
          <i style={{ width: `${percent}%` }} />
        </div>
        <b>{percent}%</b>
      </div>

      <p className="tile__note">
        Принято {thousands(state.approved)} из {thousands(state.total)}{" "}
        {plural(state.total, "сегмента", "сегментов", "сегментов")}
        {state.flagged > 0 && ` · ждут решения ${thousands(state.flagged)}`}
        {state.untouched > 0 && ` · не переведено ${thousands(state.untouched)}`}
      </p>
    </section>
  );
}

/** Отбор по виду замечания.
 *
 * Числа рядом с видами считаются по всей книге, а не по показанной полусотне:
 * по ним судят о том, сколько работы осталось.
 */
function Filters({
  documentId,
  state,
  check,
}: {
  documentId: string;
  state: ReviewProgress;
  check?: string;
}) {
  const present = CHECKS.filter((kind) => (state.by_check[kind] ?? 0) > 0);

  if (present.length < 2) {
    return null;
  }

  return (
    <div className="wk-filter">
      <Link
        className={check === undefined ? "is-active" : ""}
        href={`/app/queue?document=${documentId}`}
      >
        Все · {thousands(state.flagged)}
      </Link>

      {present.map((kind) => (
        <Link
          className={check === kind ? "is-active" : ""}
          key={kind}
          href={`/app/queue?document=${documentId}&check=${kind}`}
        >
          {CHECK_LABEL[kind] ?? kind} · {thousands(state.by_check[kind] ?? 0)}
        </Link>
      ))}
    </div>
  );
}

/** Очередь пуста — но по разным причинам, и путать их нельзя. */
function Nothing({
  state,
  book,
  check,
}: {
  state: ReviewProgress;
  book: Document;
  check?: string;
}) {
  if (check !== undefined) {
    return (
      <section className="tile wk-call">
        <h3>По этому виду замечаний ничего не осталось</h3>
        <p>
          Разобрано всё, к чему придрался этот вид проверки. Остальные виды —
          по кнопкам выше.
        </p>
        <div className="tile__foot">
          <Link className="btn btn--ghost btn--small" href={`/app/queue?document=${book.id}`}>
            Ко всей очереди
          </Link>
        </div>
      </section>
    );
  }

  if (state.untouched > 0) {
    return (
      <section className="tile wk-call">
        <h3>Замечаний нет, но книга переведена не вся</h3>
        <p>
          Проверки ни к чему не придрались в переведённой части, а{" "}
          {thousands(state.untouched)}{" "}
          {plural(state.untouched, "сегмент ещё ждёт", "сегмента ещё ждут", "сегментов ещё ждут")}{" "}
          перевода. Замечания по ним появятся здесь после того, как их
          переведут.
        </p>
        <div className="tile__foot">
          <Link className="btn btn--primary btn--small" href={`/app/documents/${book.id}`}>
            К книге
          </Link>
        </div>
      </section>
    );
  }

  if (state.is_complete) {
    return (
      <section className="tile wk-call">
        <h3>Книга принята целиком</h3>
        <p>
          Все {thousands(state.total)}{" "}
          {plural(state.total, "сегмент принят", "сегмента приняты", "сегментов приняты")}
          человеком. Дальше — выгрузка: файл соберётся обратно в исходном виде,
          переведённым.
        </p>
        <div className="tile__foot">
          <Link className="btn btn--ghost btn--small" href={`/app/documents/${book.id}`}>
            К книге
          </Link>
        </div>
      </section>
    );
  }

  return (
    <section className="tile wk-call">
      <h3>Проверки ни к чему не придрались</h3>
      <p>
        Числа сошлись, подстановки на месте, термины употреблены. Осталось
        принять перевод — это отдельное действие: «проверки промолчали» и «я за
        это отвечаю» не одно и то же.
      </p>
    </section>
  );
}
