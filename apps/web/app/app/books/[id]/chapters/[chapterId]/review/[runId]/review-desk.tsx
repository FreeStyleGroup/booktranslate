"use client";

/* Рабочее место редактора: одно место за раз.

   Ключ компонента — редакция блока или сумма объекта: новый текст сбрасывает всё, что было в форме,
   и сравнивать приходится заново. Литературная правка сначала спрашивает у сервера, что она задевает:
   предупредить проще, чем отказать. Сохранение проверит то же самое ещё раз, браузеру здесь не верят. */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import type {
  EditReason,
  ReviewNextBlock,
  ReviewNextObject,
  ReviewOpenIssue,
  ReviewRun,
} from "../../../../../../../lib/work";
import {
  EDIT_REASON_HINT,
  EDIT_REASON_LABEL,
  EDIT_REASON_ORDER,
  ISSUE_SEVERITY_CHIP,
  ISSUE_SEVERITY_LABEL,
  ISSUE_STATUS_LABEL,
  KIND_ONE,
  OBJECT_ONE,
  plural,
  thousands,
} from "../../../../../../labels";
import { RegisterIssue } from "../../../../../../issues/register-issue";
import { ReportError, useToast } from "../../../../../../ui/toast";
import { CopyId } from "../../../../../../ui/copy-id";
import {
  completeReview,
  markReviewBlock,
  markReviewObject,
  previewLiteraryEdit,
  saveLiteraryEdit,
  type ReviewResult,
} from "../../../../../review-actions";

const RELATION: Record<string, string> = {
  content: "блок стоит в объекте",
  caption: "подпись объекта",
  reference: "ссылка в тексте",
};

function Issues({ items }: { items: ReviewOpenIssue[] }) {
  if (items.length === 0) {
    return null;
  }

  return (
    <div>
      <h4 className="is-subhead">Незакрытые замечания этого места</h4>
      <ul className="bk-review__list">
        {items.map((item) => (
          <li key={item.id}>
            <Link href={`/app/issues/${item.id}`}>{item.code}</Link>{" "}
            <span className={ISSUE_SEVERITY_CHIP[item.severity]}>
              {ISSUE_SEVERITY_LABEL[item.severity]}
            </span>{" "}
            <span className="tile__note">{ISSUE_STATUS_LABEL[item.status]}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Pair({
  source,
  translation,
  title,
  code,
}: {
  source: string;
  translation: string | null;
  title: string;
  code: boolean;
}) {
  const Body = code ? "pre" : "p";
  const style = code ? "bk-block-code" : "bk-block-text";

  return (
    <div className="is-pair bk-review__pair">
      <div>
        <h4>Оригинал</h4>
        <Body className={style}>{source}</Body>
      </div>
      <div>
        <h4>{title}</h4>
        {translation === null ? (
          <p className="tile__note">Перевода нет.</p>
        ) : (
          <Body className={style}>{translation}</Body>
        )}
      </div>
    </div>
  );
}

function useAct(): {
  pending: boolean;
  error: string | null;
  act: (action: () => Promise<ReviewResult>, done: () => void) => void;
} {
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const router = useRouter();

  function act(action: () => Promise<ReviewResult>, done: () => void): void {
    setError(null);

    start(async () => {
      const result = await action();

      if (result.error !== undefined) {
        setError(result.error);
        // Отказ мог быть конфликтом: на странице должен оказаться нынешний текст.
        router.refresh();
        return;
      }

      done();
    });
  }

  return { pending, error, act };
}

export function BlockDesk({
  bookId,
  chapterId,
  run,
  block,
  canMark,
  here,
}: {
  bookId: string;
  chapterId: string;
  run: ReviewRun;
  block: ReviewNextBlock;
  canMark: boolean;
  here: string;
}) {
  const { pending, error, act } = useAct();
  const router = useRouter();

  const chapterHref = `/app/books/${bookId}/chapters/${chapterId}`;
  const nextHref = `${here}?after=${block.ordinal}`;

  function mark(result: "ok" | "issue"): void {
    act(
      () => markReviewBlock(bookId, chapterId, run.id, block.id, block.revision_id, result),
      () => {
        router.push(nextHref);
      },
    );
  }

  const before = block.context.filter((row) => row.ordinal < block.ordinal);
  const later = block.context.filter((row) => row.ordinal > block.ordinal);

  return (
    <>
      <section className="tile">
        <div className="tile__head">
          <h3 className="bk-review__code">
            <CopyId value={block.code} title="код блока" />
          </h3>
          <span className="bk-tools__side">
            <span className="tile__note">
              {KIND_ONE[block.kind] ?? block.kind} · редакция {block.revision_no}
            </span>
            <Link className="tile__note" href={`${chapterHref}/translation/${block.id}`}>
              История
            </Link>
          </span>
        </div>

        <Pair
          source={block.source_text}
          translation={block.text}
          title="Перевод"
          code={block.kind === "code"}
        />

        <div className="wk-actions">
          {canMark && (
            <button
              className="btn btn--primary"
              type="button"
              disabled={pending}
              onClick={() => mark("ok")}
            >
              Всё верно, дальше
            </button>
          )}
          <Link className="btn btn--ghost" href={nextHref} prefetch={false}>
            Следующий непроверенный
          </Link>
        </div>

        <ReportError error={error} />
      </section>

      {canMark && run.kind === "literary" && (
        <LiteraryForm bookId={bookId} chapterId={chapterId} runId={run.id} block={block} />
      )}

      {canMark && (
        <RegisterIssue
          blockId={block.id}
          category={run.kind === "technical" ? "technical" : "translation"}
          onRegistered={() => mark("issue")}
        />
      )}

      <section className="tile">
        <div className="tile__head">
          <h3>Рядом</h3>
        </div>

        <div className={block.issues.length > 0 ? "bk-review__side is-three" : "bk-review__side"}>
          <Issues items={block.issues} />

          <div>
            <h4 className="is-subhead">Термины</h4>
            {block.terms.length === 0 ? (
              <p className="tile__note">В этом блоке терминов из глоссария нет.</p>
            ) : (
              <ul className="bk-review__list">
                {block.terms.map((term) => (
                  <li key={term.source}>
                    {term.source} → <b>{term.target}</b>{" "}
                    {term.mandatory && <span className="chip chip--warn">обязательный</span>}
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div>
            <h4 className="is-subhead">Объекты</h4>
            {block.objects.length === 0 ? (
              <p className="tile__note">Блок не связан с объектами.</p>
            ) : (
              <ul className="bk-review__list">
                {block.objects.map((item) => (
                  <li key={item.id}>
                    <Link
                      href={`/app/books/${bookId}/chapters/${item.chapter_id}/objects/${item.id}`}
                    >
                      {item.code}
                    </Link>{" "}
                    <span className="tile__note">
                      {OBJECT_ONE[item.type]}, {RELATION[item.relation] ?? item.relation}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>

        <Context title="Перед этим блоком" rows={before} />
        <Context title="После этого блока" rows={later} />
      </section>
    </>
  );
}

function Context({ title, rows }: { title: string; rows: ReviewNextBlock["context"] }) {
  if (rows.length === 0) {
    return null;
  }

  return (
    <div className="bk-review__context">
      <h4 className="is-subhead">{title}</h4>
      {rows.map((row) => (
        <div key={row.code}>
          <p className="tile__note">{row.code}</p>
          <div className="is-pair">
            <p className="bk-block-text">{row.source_text}</p>
            <p className="bk-block-text">{row.translation ?? <i>перевода нет</i>}</p>
          </div>
        </div>
      ))}
    </div>
  );
}

/* Литературная правка. */

function LiteraryForm({
  bookId,
  chapterId,
  runId,
  block,
}: {
  bookId: string;
  chapterId: string;
  runId: string;
  block: ReviewNextBlock;
}) {
  const [text, setText] = useState(block.text);
  const [reason, setReason] = useState<EditReason>("style");
  const [issueId, setIssueId] = useState("");
  const [note, setNote] = useState("");
  const [violations, setViolations] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const router = useRouter();
  const toast = useToast();

  if (block.protected) {
    return (
      <section className="tile">
        <div className="tile__head">
          <h3>Литературная правка</h3>
        </div>
        <p className="tile__note">
          Этот блок переносится знак в знак: код и формулы в литературной редактуре не правятся.
        </p>
      </section>
    );
  }

  async function persist(acceptViolation: boolean): Promise<void> {
    const saved = await saveLiteraryEdit(bookId, chapterId, runId, {
      blockId: block.id,
      baseRevisionId: block.revision_id,
      text,
      reason,
      note,
      issueId: issueId === "" ? null : issueId,
      acceptViolation,
    });

    if (saved.error !== undefined) {
      setError(saved.error);
      router.refresh();
      return;
    }

    toast.ok(
      acceptViolation
        ? "Правка сохранена, заведено техническое замечание"
        : "Правка сохранена: блок снова в очереди",
    );
    router.refresh();
  }

  function submit(): void {
    setError(null);

    start(async () => {
      const found = await previewLiteraryEdit(runId, block.id, block.revision_id, text);

      if (found.error !== undefined) {
        setError(found.error);
        router.refresh();
        return;
      }

      const list = found.violations ?? [];
      setViolations(list);

      if (list.length === 0) {
        await persist(false);
      }
    });
  }

  const changed = text.trim() !== "" && text.trim() !== block.text;

  return (
    <section className="tile">
      <div className="tile__head">
        <h3>Литературная правка</h3>
      </div>

      <p className="tile__note">
        Появится новая редакция, прежняя останется в истории. Правленый блок вернётся в очередь: его
        нужно будет посмотреть уже в новом виде.
      </p>

      <form
        className="is-form"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <label className="field">
          <span>Новый текст</span>
          <textarea
            value={text}
            required
            maxLength={100000}
            rows={Math.min(12, Math.max(3, Math.ceil(block.text.length / 70)))}
            onChange={(event) => {
              setText(event.target.value);
              setViolations([]);
            }}
          />
        </label>

        <div className="is-form__row">
          <label className="field">
            <span>Зачем правка</span>
            <select
              value={reason}
              onChange={(event) => setReason(event.target.value as EditReason)}
            >
              {EDIT_REASON_ORDER.map((value) => (
                <option key={value} value={value}>
                  {EDIT_REASON_LABEL[value]}
                </option>
              ))}
            </select>
            <small>{EDIT_REASON_HINT[reason]}</small>
          </label>

          {block.issues.length > 0 && (
            <label className="field">
              <span>По замечанию, если правка из-за него</span>
              <select value={issueId} onChange={(event) => setIssueId(event.target.value)}>
                <option value="">Без замечания</option>
                {block.issues.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.code}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>

        {violations.length > 0 && (
          <div className="bk-mismatch" role="alert">
            <span aria-hidden="true">⚠</span>
            <div>
              <p>Правка меняет то, что стилем не считается:</p>
              <ul className="bk-gate__list">
                {violations.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
              <p>
                Верните это или сохраните с причиной: заведётся техническое замечание, и оно будет
                держать финальную сверку.
              </p>
            </div>
          </div>
        )}

        {violations.length > 0 && (
          <label className="field">
            <span>Почему меняете защищённое</span>
            <textarea
              value={note}
              required
              maxLength={4000}
              rows={2}
              onChange={(event) => setNote(event.target.value)}
            />
          </label>
        )}

        <div className="wk-actions">
          {violations.length === 0 ? (
            <button className="btn btn--primary" type="submit" disabled={pending || !changed}>
              {pending ? "Сохраняем…" : "Сохранить правку"}
            </button>
          ) : (
            <button
              className="btn btn--primary"
              type="button"
              disabled={pending || note.trim() === ""}
              onClick={() => {
                setError(null);
                start(() => persist(true));
              }}
            >
              Сохранить и завести замечание
            </button>
          )}
        </div>

        <ReportError error={error} />
      </form>
    </section>
  );
}

/* Объект. */

export function ObjectDesk({
  bookId,
  chapterId,
  run,
  item,
  canMark,
  here,
}: {
  bookId: string;
  chapterId: string;
  run: ReviewRun;
  item: ReviewNextObject;
  canMark: boolean;
  here: string;
}) {
  const { pending, error, act } = useAct();
  const router = useRouter();
  const nextHref = `${here}?after_object=${item.position}`;

  function mark(result: "ok" | "issue"): void {
    act(
      () =>
        markReviewObject(bookId, chapterId, run.id, item.id, item.content_hash, result),
      () => {
        router.push(nextHref);
      },
    );
  }

  return (
    <>
      <section className="tile">
        <div className="tile__head">
          <h3 className="bk-review__code">
            <CopyId value={item.code} title="код объекта" />
          </h3>
          <span className="bk-tools__side">
            <span className="tile__note">{OBJECT_ONE[item.type]}</span>
            <Link
              className="tile__note"
              href={`/app/books/${bookId}/chapters/${chapterId}/objects/${item.id}`}
            >
              Открыть объект
            </Link>
          </span>
        </div>

        <Pair
          source={item.source_text}
          translation={item.translation}
          title="Перевод"
          code={item.type === "code"}
        />

        <Issues items={item.issues} />

        <div className="wk-actions">
          {canMark && (
            <button
              className="btn btn--primary"
              type="button"
              disabled={pending}
              onClick={() => mark("ok")}
            >
              Всё верно, дальше
            </button>
          )}
          <Link className="btn btn--ghost" href={nextHref} prefetch={false}>
            Следующий непроверенный
          </Link>
        </div>

        <ReportError error={error} />
      </section>

      {canMark && (
        <RegisterIssue
          objectId={item.id}
          category={item.type === "table" ? "table" : item.type === "equation" ? "formula" : "figure"}
          onRegistered={() => mark("issue")}
        />
      )}
    </>
  );
}

/* Конец очереди. */

export function FinishDesk({
  bookId,
  chapterId,
  run,
  canMark,
  chapterHref,
}: {
  bookId: string;
  chapterId: string;
  run: ReviewRun;
  canMark: boolean;
  chapterHref: string;
}) {
  const { pending, error, act } = useAct();
  const router = useRouter();
  const toast = useToast();

  return (
    <section className="tile">
      <div className="tile__head">
        <h3>{run.complete ? "Просмотрено всё" : "Очередь пуста"}</h3>
      </div>

      {run.untranslated > 0 ? (
        <p className="tile__note">
          Без перевода осталось {thousands(run.untranslated)}{" "}
          {plural(run.untranslated, "блок", "блока", "блоков")}: смотреть там нечего, и завершить
          работу нельзя, пока они не переведены.
        </p>
      ) : (
        <p className="tile__note">
          Завершение закрепит этот текст. Если он потом изменится, работа будет помечена как
          устаревшая.
          {run.kind !== "literary" &&
            " Незакрытые критичные и серьёзные замечания завершить не дадут."}
          {run.kind === "literary" && " Сразу после завершения запустится формальная проверка."}
        </p>
      )}

      <div className="wk-actions">
        {canMark && run.complete && (
          <button
            className="btn btn--primary"
            type="button"
            disabled={pending}
            onClick={() =>
              act(
                () => completeReview(bookId, chapterId, run.id),
                () => {
                  toast.ok("Работа завершена");
                  router.push(chapterHref);
                },
              )
            }
          >
            Завершить
          </button>
        )}
        <Link className="btn btn--ghost" href={`/app/issues?book=${bookId}&chapter=${chapterId}`}>
          Замечания главы
        </Link>
        <Link className="btn btn--ghost" href={chapterHref}>
          К главе
        </Link>
      </div>

      <ReportError error={error} />
    </section>
  );
}
