import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import {
  load,
  type Document,
  type DocumentProfile,
  type Project,
  type SegmentPage,
} from "../../../lib/work";
import {
  CHECK_CHIP,
  CHECK_LABEL,
  DOCUMENT_CHIP,
  DOCUMENT_LABEL,
  FORMAT_LABEL,
  KIND_LABEL,
  KIND_ONE,
  SEGMENT_COLOR,
  SEGMENT_LABEL,
  fileSize,
  pages,
  plural,
  thousands,
  when,
} from "../../labels";
import "../../work.css";
import { DeleteButton, ParseButton } from "../actions-ui";
import { BeforeTranslate, TranslateRun } from "../translate-run";

export const metadata: Metadata = {
  title: "Документ — BookTranslate",
  description: "Состав книги, смета на перевод и разбор на сегменты.",
};

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// Сколько сегментов показывать сразу. Книга — это тысячи сегментов, и
// вываливать их все незачем: здесь смотрят, ЧТО получилось из файла, а не
// читают книгу.
const PREVIEW = 20;

// Форматы, которые принимаются, но пока не разбираются. Сказать об этом на
// карточке честнее, чем дать нажать «разобрать» и ответить отказом.
const NOT_PARSED_YET: Record<string, string> = {
  pdf: "PDF пока не разбирается: это не разметка, а описание того, где какая буква нарисована, и абзацы с колонками в нём приходится восстанавливать. Пришлите DOCX или EPUB, если они есть.",
  xliff:
    "XLIFF пока не разбирается: он уже разбит на сегменты кем-то другим, и переносить надо чужую разбивку вместе со статусами, а не нарезать заново.",
};

export default async function DocumentPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ same?: string }>;
}) {
  const { id } = await params;
  // Пришли сюда после повторной загрузки того же файла: API отдал
  // заведённый документ вместо копии, и об этом надо сказать.
  const { same } = await searchParams;

  if (!UUID.test(id)) {
    notFound();
  }

  const here = `/app/documents/${id}`;
  const document = await load<Document>(`/documents/${id}`, here);

  if (document.error !== undefined) {
    return (
      <section className="tile">
        <h2>Документ</h2>
        <p className="tile__empty">{document.error}</p>
        <div className="tile__foot">
          <Link className="btn btn--ghost btn--small" href="/app/documents">
            К списку
          </Link>
        </div>
      </section>
    );
  }

  const book = document.data;
  const project = await load<Project>(`/projects/${book.project_id}`, here);
  const profile = await load<DocumentProfile>(`/documents/${id}/profile`, here);
  const segments = await load<SegmentPage>(
    `/documents/${id}/segments?limit=${PREVIEW}`,
    here,
  );

  const parsed = book.status !== "uploaded" && book.status !== "failed";
  const blocked = NOT_PARSED_YET[book.source_format];

  return (
    <>
      <header className="wk-head">
        <div>
          <p className="wk-crumbs">
            <Link href="/app/documents">Документы</Link>
            {project.data !== undefined && (
              <>
                <span aria-hidden="true"> · </span>
                <Link href={`/app/documents?project=${book.project_id}`}>
                  {project.data.name}
                </Link>
              </>
            )}
          </p>

          <h1>{book.title}</h1>

          <p className="tile__note">
            {FORMAT_LABEL[book.source_format] ?? book.source_format} ·{" "}
            {fileSize(book.size_bytes)} · загружен {when(book.created_at)}
            {project.data !== undefined && (
              <>
                {" "}
                · {project.data.source_language} → {project.data.target_language}
              </>
            )}
          </p>
        </div>

        <span className={DOCUMENT_CHIP[book.status] ?? "chip chip--info"}>
          {DOCUMENT_LABEL[book.status] ?? book.status}
        </span>
      </header>

      {same === "1" && (
        <p className="wk-note" role="status">
          <span aria-hidden="true">📌</span> Этот файл уже загружали — вот он.
          Второй копии не завелось, и за повторный разбор платить не пришлось.
        </p>
      )}

      {book.error !== null && (
        <p className="form__error" role="alert">
          {book.error}
        </p>
      )}

      {blocked !== undefined ? (
        <section className="tile wk-call">
          <h3>Этот формат пока не разбираем</h3>
          <p>{blocked}</p>
        </section>
      ) : (
        !parsed && (
          <section className="tile wk-call">
            <h3>Файл принят. Следующий шаг — разбор</h3>
            <p>
              Разбор делит книгу на сегменты: абзацы, заголовки, пункты списков,
              ячейки таблиц. Дальше всё считается по ним — объём, повторы,
              готовность и цена. Оформление при этом остаётся: файл соберётся
              обратно в том же виде, переведённым.
            </p>
            <div className="tile__foot">
              <ParseButton id={book.id} label="Разобрать" />
            </div>
          </section>
        )
      )}

      {parsed && profile.data !== undefined && (
        <Passport profile={profile.data} book={book} />
      )}

      {parsed && <NextStep book={book} profile={profile.data} />}

      {parsed && segments.data !== undefined && segments.data.items.length > 0 && (
        <Preview page={segments.data} profile={profile.data} />
      )}

      <section className="tile">
        <div className="tile__head">
          <h3>Действия</h3>
          <span className="tile__note">исходный файл хранится целиком</span>
        </div>

        <div className="tile__foot">
          <a
            className="btn btn--ghost btn--small"
            href={`/api/documents/${book.id}/source`}
            download
          >
            Скачать исходник
          </a>

          {parsed && blocked === undefined && (
            <ParseButton id={book.id} again small label="Разобрать заново" />
          )}

          <DeleteButton id={book.id} title={book.title} small />
        </div>

        {parsed && (
          <p className="tile__note wk-warn">
            Разбор заново удаляет существующие сегменты вместе с переводом и
            правкой. Нужен он там, где заказчик прислал исправленный файл.
          </p>
        )}
      </section>
    </>
  );
}

/* Первые сегменты книги.

   До перевода это ответ на вопрос «что получилось из файла»: видно, что
   заголовок стал заголовком, а таблица — ячейками. После перевода это
   единственное место, где перевод вообще можно увидеть, пока не сделана
   очередь замечаний, — поэтому рядом с исходником появляется вторая
   колонка, а не отдельный экран. */
function Preview({ page, profile }: { page: SegmentPage; profile?: DocumentProfile }) {
  const translated = page.items.some((segment) => segment.target_text !== null);

  return (
    <section className="tile">
      <div className="tile__head">
        <h3>{translated ? "Перевод по сегментам" : "Как файл разобрался"}</h3>
        <span className="tile__note">
          первые {page.items.length} из {thousands(page.total)}
        </span>
      </div>

      <div className={translated ? "wk-seg wk-seg--pair" : "wk-seg"}>
        {page.items.map((segment) => (
          <div className="wk-seg__row" key={segment.id}>
            <span className="wk-seg__no">{segment.position + 1}</span>
            <span className="wk-seg__kind">
              <i style={{ background: SEGMENT_COLOR[segment.status] ?? "#94a3b8" }} />
              {KIND_ONE[segment.kind] ?? segment.kind}
            </span>
            <span className="wk-seg__text">{segment.source_text}</span>
            {translated && (
              <span className="wk-seg__dst">
                {segment.target_text ?? "—"}
                {/* Находки проверок показываем рядом с переводом: они и
                    относятся к нему, а не к исходнику. */}
                {(segment.quality?.findings ?? []).slice(0, 2).map((finding) => (
                  <span
                    key={finding.check}
                    className={CHECK_CHIP[finding.check] ?? "chip chip--warn"}
                    title={finding.message}
                  >
                    {CHECK_LABEL[finding.check] ?? finding.check}
                  </span>
                ))}
              </span>
            )}
          </div>
        ))}
      </div>

      <p className="tile__note wk-seg__foot">
        Цветом слева помечено состояние сегмента
        {profile !== undefined && `: ${statuses(profile)}`}.
      </p>
    </section>
  );
}

/* Что делать с книгой дальше.

   Одна карточка на три случая, а не три подряд: у книги в каждый момент
   ровно один следующий шаг, и показывать рядом «решите термины» и
   «переведите» значит предлагать сделать то, что всё равно не выйдет. */
function NextStep({ book, profile }: { book: Document; profile?: DocumentProfile }) {
  const waiting = profile?.undecided_terms ?? 0;

  if (waiting > 0) {
    return (
      <section className="tile wk-call">
        <h3>
          {thousands(waiting)} {plural(waiting, "термин", "термина", "терминов")} ждёт
          решения
        </h3>
        <p>
          Пока они не решены, перевод не начнётся. Это не придирка: слово,
          отданное модели на усмотрение, в сорока сегментах будет названо
          по-разному, и ловить это потом придётся тому, кто читал исходник.
        </p>
        <div className="tile__foot">
          <Link className="btn btn--primary btn--small" href={`/app/terms?document=${book.id}`}>
            Разобрать термины
          </Link>
        </div>
      </section>
    );
  }

  /* Проход по книге ещё не делался: кандидатов нет вовсе, и это не то же
     самое, что «все решены». Пока он не сделан, перевод формально
     возможен — API молчит, когда кандидатов нет, — но заводить книгу без
     терминологии значит получить сорок написаний одного слова. */
  const started = (profile?.segments ?? 0) > 0 && profile !== undefined;

  if (started && !hasTerms(profile) && (profile?.untranslated ?? 0) > 0) {
    return (
      <BeforeTranslate documentId={book.id} untranslated={profile?.untranslated ?? 0} />
    );
  }

  if (profile !== undefined && profile.untranslated === 0) {
    const flagged = profile.by_status.flagged ?? 0;

    return (
      <section className="tile wk-call">
        <h3>Книга переведена</h3>
        <p>
          {flagged === 0
            ? "Непереведённых сегментов не осталось, и проверки ни к чему не придрались."
            : `Непереведённых сегментов не осталось. ${thousands(flagged)} ${plural(
                flagged,
                "сегмент ждёт",
                "сегмента ждут",
                "сегментов ждут",
              )} человека: проверки нашли расхождение чисел, нарушение термина или потерянную подстановку. Это не приговор переводу, а список мест, на которые стоит посмотреть.`}
        </p>
        <div className="tile__foot">
          <Link className="btn btn--ghost btn--small" href="/app/queue">
            Очередь замечаний
          </Link>
        </div>
      </section>
    );
  }

  return (
    <TranslateRun documentId={book.id} untranslated={profile?.untranslated ?? 0} />
  );
}

/* Делался ли по книге терминологический проход. Состояния три, а не два:
   «проход не делался», «есть нерешённые» и «всё решено» — и следующий шаг
   у них разный. Нерешённые ловятся выше, здесь остаётся отличить
   непройденную книгу от пройденной. */
function hasTerms(profile: DocumentProfile | undefined): boolean {
  return profile !== undefined && profile.terms_total > 0;
}

/** Состояния сегментов словами: «не переведено — 1 240, принято — 12». */
function statuses(profile: DocumentProfile): string {
  return Object.entries(profile.by_status)
    .sort(([, first], [, second]) => second - first)
    .map(([status, amount]) => `${SEGMENT_LABEL[status] ?? status} — ${thousands(amount)}`)
    .join(", ");
}

/* Паспорт книги: объём, состав и смета.

   Отвечает на единственный вопрос, который задают до начала работы: что
   это за файл и во что он обойдётся. Всё остальное — потом. */
function Passport({ profile, book }: { profile: DocumentProfile; book: Document }) {
  if (profile.segments === 0) {
    return (
      <section className="tile">
        <p className="tile__empty">
          Разбор прошёл, но текста в файле не нашлось. Так бывает с
          отсканированными страницами: буквы в них нарисованы картинкой, и
          распознавание — отдельная работа.
        </p>
      </section>
    );
  }

  const kinds = Object.entries(profile.by_kind).sort(([, a], [, b]) => b - a);
  const done = profile.untranslated === 0;

  return (
    <>
      <div className="wk-facts">
        <Fact
          value={thousands(profile.segments)}
          label={plural(profile.segments, "сегмент", "сегмента", "сегментов")}
          mark="🧩"
        />
        <Fact
          value={thousands(pages(profile.characters))}
          label={plural(
            pages(profile.characters),
            "учётная страница",
            "учётные страницы",
            "учётных страниц",
          )}
          mark="📄"
        />
        <Fact
          value={thousands(profile.words)}
          label={plural(profile.words, "слово", "слова", "слов")}
          mark="🔤"
        />
        <Fact
          value={thousands(profile.characters)}
          label={plural(profile.characters, "знак", "знака", "знаков")}
          mark="📏"
        />
      </div>

      <div className="cab__row cab__row--split">
        <section className="tile">
          <div className="tile__head">
            <h3>Из чего состоит</h3>
            <span className="tile__note">по роли в книге</span>
          </div>

          <div className="wk-kinds">
            {kinds.map(([kind, amount]) => (
              <div className="wk-kind" key={kind}>
                <span>{KIND_LABEL[kind] ?? kind}</span>
                <div className="bar">
                  <i style={{ width: `${(amount * 100) / profile.segments}%` }} />
                </div>
                <b>{thousands(amount)}</b>
              </div>
            ))}
          </div>

          <p className="tile__note wk-seg__foot">
            Самый длинный сегмент — {thousands(profile.longest_segment_chars)} знаков.
            Роль важна: заголовок переводится не так, как предупреждение, и
            проверяется строже.
          </p>
        </section>

        <section className="tile">
          <div className="tile__head">
            <h3>{done ? "Во что обошёлся перевод" : "Во что обойдётся перевод"}</h3>
            <span className="tile__note">{done ? "по факту" : "оценка сверху"}</span>
          </div>

          {/* У переведённой книги сметы больше нет: четыре нуля подряд
              ничего не объясняют, а объясняет потраченное. */}
          {done ? <Spent book={book} /> : <Estimate profile={profile} />}
        </section>
      </div>
    </>
  );
}

/* Сколько будет стоить перевод того, что осталось. */
function Estimate({ profile }: { profile: DocumentProfile }) {
  return (
    <>
      <div className="wk-money">
        <div className="wk-money__row">
          <span>Сегментов к переводу</span>
          <b>{thousands(profile.untranslated)}</b>
        </div>
        <div className="wk-money__row">
          <span>Повторяются внутри книги</span>
          <b>{thousands(profile.repeated)}</b>
        </div>
        <div className="wk-money__row">
          <span>Уже есть в памяти переводов</span>
          <b>{thousands(profile.memory_matches)}</b>
        </div>
        <div className="wk-money__row wk-money__row--total">
          <span>Оплачивается</span>
          <b>{thousands(profile.billable_texts)}</b>
        </div>
      </div>

      <p className="tile__note wk-seg__foot">
        Повтор и совпадение с памятью переводятся один раз на всю книгу,
        поэтому оплачивается {thousands(profile.billable_texts)} из{" "}
        {thousands(profile.untranslated)}. Одинаковый текст обязан звучать
        одинаково — деньги тут приятное следствие, а не цель.
      </p>

      {profile.estimate !== null && (
        <p className="wk-price">
          {profile.estimate.usd === null ? (
            <>
              <b>{thousands(profile.estimate.input_tokens)}</b> токенов на входе
              <span className="tile__note"> · цена неизвестна: модель не в прейскуранте</span>
            </>
          ) : (
            <>
              <b>≈ ${profile.estimate.usd.toFixed(2)}</b>
              <span className="tile__note">
                {" "}
                · {thousands(profile.estimate.input_tokens)} токенов на входе,{" "}
                {thousands(profile.estimate.output_tokens)} на выходе
              </span>
            </>
          )}
        </p>
      )}

      <p className="tile__note wk-seg__foot">
        Смета считается с запасом и по прейскуранту модели в долларах.
        Настоящий счёт приходит от поставщика и бывает меньше; число здесь
        годится, чтобы назначить цену заказчику, а не чтобы сверять с
        выставленным счётом.
      </p>
    </>
  );
}

/* Что книга стоила на самом деле.

   Токены, а не деньги: цены меняются, а потраченное на эту книгу —
   исторический факт. Стоимость считает API по прейскуранту той модели,
   которой переводили. */
function Spent({ book }: { book: Document }) {
  /* Ноль токенов означает разное, и путать это нельзя. Если переводчик не
     записан — модель не вызывалась вовсе: всё закрыли память и повторы.
     Если записан, а токенов нет — переводил провайдер, который ничего не
     тратит (заглушка разработки). Сказать в этом случае «модель не
     вызывалась» значит соврать в отчёте о работе, которая была сделана. */
  if (book.input_tokens + book.output_tokens === 0) {
    return (
      <p className="tile__empty">
        {book.translated_by === null
          ? "Переводить было нечего: все сегменты закрыты памятью переводов и повторами. Модель не вызывалась ни разу."
          : `Расхода нет: переводил «${book.translated_by}» — этот провайдер ничего не тратит. Настоящая модель включается настройкой TRANSLATION_PROVIDER.`}
      </p>
    );
  }

  return (
    <>
      <div className="wk-money">
        <div className="wk-money__row">
          <span>Токенов на входе</span>
          <b>{thousands(book.input_tokens)}</b>
        </div>
        <div className="wk-money__row">
          <span>Токенов на выходе</span>
          <b>{thousands(book.output_tokens)}</b>
        </div>
        {book.cached_input_tokens > 0 && (
          <div className="wk-money__row">
            <span>Прочитано из кэша</span>
            <b>{thousands(book.cached_input_tokens)}</b>
          </div>
        )}
      </div>

      <p className="tile__note wk-seg__foot">
        {book.translated_by === null
          ? "Модель не записана."
          : `Переведено моделью ${book.translated_by}.`}{" "}
        Хранятся токены, а не деньги: цены меняются, а потраченное на эту
        книгу — исторический факт, и пересчитывать его задним числом по
        новому прейскуранту значит подделывать отчёт.
      </p>
    </>
  );
}

function Fact({ value, label, mark }: { value: string; label: string; mark: string }) {
  return (
    <section className="stat wk-fact">
      <span className="stat__mark" aria-hidden="true">
        {mark}
      </span>
      <div className="stat__value">{value}</div>
      <div className="stat__label">{label}</div>
    </section>
  );
}
