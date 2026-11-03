import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { load, type Book, type BookStructure, type ObjectDetail } from "../../../../../../../lib/work";
import { KIND_ONE, MENTION_LABEL, OBJECT_ONE, shortHash, when } from "../../../../../../labels";
import "../../../../../../work.css";
import "../../../../../../ui/ui.css";
import "../../../../../books.css";
import { CopyId } from "../../../../../../ui/copy-id";
import { paramsOf } from "../../../../../../ui/query";
import { FigureImages, Formula, TableGrid } from "../../object-views";
import { VerifyObjectButton } from "../../translation/[blockId]/revision-actions";

export const metadata: Metadata = {
  title: "Объект главы — BookTranslate",
  description: "Рисунок, таблица, формула или листинг: оригинал, подпись и упоминания в тексте.",
};

/* Карточка объекта: оригинал рядом с переводом, подпись, и где он упомянут.

   Объект не правится: он появился при извлечении мастера и выводится из
   действия при следующем. Поэтому единственное действие здесь — отметить, что
   объект проверен технически. Отметка относится к тому, что проверяли:
   изменились объект или редакции его блоков — она перестаёт действовать сама. */

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default async function ObjectPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string; chapterId: string; objectId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { id, chapterId, objectId } = await params;

  if (!UUID.test(id) || !UUID.test(chapterId) || !UUID.test(objectId)) {
    notFound();
  }

  const version = paramsOf(await searchParams).get("version");
  const chapterPath = `/app/books/${id}/chapters/${chapterId}`;
  const here = `${chapterPath}/objects/${objectId}`;
  const inVersion = version !== null && UUID.test(version) ? version : null;

  const [book, structure, found] = await Promise.all([
    load<Book>(`/books/${id}`, here),
    load<BookStructure>(`/books/${id}/chapters`, here),
    load<ObjectDetail>(
      `/objects/${objectId}${inVersion !== null ? `?master_id=${inVersion}` : ""}`,
      here,
    ),
  ]);

  const chapter = structure.data?.chapters.find((item) => item.id === chapterId);

  if (found.error !== undefined || book.error !== undefined || chapter === undefined) {
    return (
      <section className="tile">
        <h2>Объект главы</h2>
        <p className="tile__empty">{found.error ?? book.error ?? "Глава не найдена"}</p>
        <div className="tile__foot">
          <Link className="btn btn--ghost btn--small" href={chapterPath}>
            К главе
          </Link>
        </div>
      </section>
    );
  }

  const item = found.data;
  const name = OBJECT_ONE[item.type] ?? item.type;
  const blockLink = (code: string) =>
    `/app/find?book=${id}&code=${encodeURIComponent(code)}`;

  return (
    <>
      <header className="wk-head">
        <div>
          <p className="wk-crumbs">
            <Link href="/app/books">Книги</Link>
            <span aria-hidden="true"> · </span>
            <Link href={`/app/books/${id}`}>{book.data.title}</Link>
            <span aria-hidden="true"> · </span>
            <Link href={`${chapterPath}?tab=${item.type}`}>
              {chapter.title ?? `Глава ${chapter.ordinal}`}
            </Link>
          </p>

          <h1>{item.label !== null ? `${name} ${item.label}` : name}</h1>

          <p className="tile__note">
            в версии мастера {item.master_label}
            {item.before_code !== null ? ` · стоит перед ${item.before_code}` : " · в конце главы"}
          </p>
        </div>

        <div className="bk-head__side">
          <CopyId value={item.full_code} title="код объекта" />
          <span className={item.active ? "chip chip--ok" : "chip chip--warn"}>
            {item.active ? "в текущей версии" : "выведен из действия"}
          </span>
        </div>
      </header>

      <section className="tile">
        <div className="tile__head">
          <h3>Оригинал</h3>
          <span className="tile__note">
            сумма{" "}
            <CopyId
              value={item.checksum}
              title="контрольную сумму объекта"
              label={shortHash(item.checksum)}
            />
          </span>
        </div>

        {item.type === "figure" && <FigureImages object={item} large />}

        {item.type === "table" && (
          <div className="bk-side">
            <div>
              <h4>Оригинал</h4>
              <TableGrid payload={item.payload} cells={item.content} />
            </div>
            <div>
              <h4>Перевод</h4>
              <TableGrid payload={item.payload} cells={item.content} translated />
            </div>
          </div>
        )}

        {item.type === "equation" && (
          <>
            <div className="bk-formula-card">
              <Formula payload={item.payload} />
            </div>
            <details className="bk-raw">
              <summary>
                Запись формулы ({item.payload.notation === "omml" ? "Word, OMML" : "MathML"})
              </summary>
              <pre className="bk-block-code">{item.payload.raw}</pre>
            </details>
          </>
        )}

        {item.type === "code" && (
          <>
            {item.content.map((block) => (
              <pre key={block.id} className="bk-block-code bk-block-code--wide">
                {block.text}
              </pre>
            ))}
            <p className="tile__note">
              Язык: {item.payload.language ?? "не указан"}. Листинг хранится знак в знак — отступы
              и пустые строки в нём и есть текст, поэтому в перевод он переносится без изменений.
            </p>
          </>
        )}

        <div className="tile__foot">
          {item.verification.verified ? (
            <span className="chip chip--ok">
              проверено технически
              {item.verification.verified_at !== null &&
                ` · ${when(item.verification.verified_at)}`}
              {item.verification.verified_by !== null && ` · ${item.verification.verified_by}`}
            </span>
          ) : item.verification.outdated ? (
            <span className="chip chip--warn">
              проверка устарела: содержимое или перевод изменились
            </span>
          ) : (
            <span className="tile__note">Ещё не проверено технически</span>
          )}
          {item.active && !item.verification.verified && (
            <VerifyObjectButton bookId={id} chapterId={chapterId} objectId={item.id} />
          )}
        </div>
      </section>

      <section className="tile">
        <h3>Подпись</h3>
        {item.caption_block === null ? (
          <p className="tile__empty">У объекта нет подписи.</p>
        ) : (
          <div className="bk-caption">
            <p className="bk-block-text">{item.caption_block.text}</p>
            {item.caption_block.translation !== undefined &&
              item.caption_block.translation !== null && (
                <p className="bk-block-text">{item.caption_block.translation}</p>
              )}
            <Link className="tile__note" href={blockLink(item.caption_block.full_code)}>
              {item.caption_block.full_code}
            </Link>
          </div>
        )}
        {item.parent_code !== null && (
          <p className="tile__note">
            Получился из {item.parent_code}: в новой версии мастера изменилось содержимое, и
            прежний код не переиспользуется.
          </p>
        )}
      </section>

      <section className="tile">
        <h3>Где упомянут</h3>
        {item.mentions.length === 0 ? (
          <p className="tile__empty">
            В действующем тексте книги объект не упоминается — ни ссылкой, ни по номеру.
          </p>
        ) : (
          <ul className="bk-mentions">
            {item.mentions.map((mention) => (
              <li key={mention.block.id}>
                <Link href={blockLink(mention.block.full_code)}>{mention.block.full_code}</Link>
                <span className="chip chip--info">{MENTION_LABEL[mention.kind] ?? mention.kind}</span>
                <span className="tile__note">
                  {KIND_ONE[mention.block.kind] ?? mention.block.kind} · «{mention.phrase}»
                </span>
                <p className="bk-block-text">{mention.block.text}</p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}
