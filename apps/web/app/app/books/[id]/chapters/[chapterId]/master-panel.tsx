"use client";

/* Версии мастера главы и действия над ними.

   Действий три, и ни одно не меняет текст: извлечь первую версию,
   извлечь новую — с причиной, утвердить текущую. «Изменить текст
   мастера» здесь нет и не будет: ошибка извлечения исправляется новой
   версией, а прежняя остаётся. */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import type { ChapterMaster } from "../../../../../lib/work";
import { shortHash, thousands, when } from "../../../../labels";
import { CopyId } from "../../../../ui/copy-id";
import { ReportError, useToast } from "../../../../ui/toast";
import { approveMaster, extractMaster, type Result } from "../../../actions";

export function MasterPanel({
  bookId,
  chapterId,
  approvedBoundaries,
  versions,
  shownId,
  canManage,
}: {
  bookId: string;
  chapterId: string;
  approvedBoundaries: boolean;
  /** Версии, новые первыми. */
  versions: ChapterMaster[];
  shownId: string | null;
  canManage: boolean;
}) {
  const [error, setError] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);
  const [pending, start] = useTransition();
  const router = useRouter();
  const toast = useToast();

  const current = versions[0];
  const here = `/app/books/${bookId}/chapters/${chapterId}`;

  function run(action: () => Promise<Result>, done: string): void {
    setError(null);

    start(async () => {
      const result = await action();

      if (result.error !== undefined) {
        setError(result.error);
        return;
      }

      setAsking(false);
      toast.ok(done);
      // На текущую версию: после извлечения новой открытая прежняя
      // перестала бы быть тем, что человек ожидает увидеть.
      router.push(here);
      router.refresh();
    });
  }

  if (!approvedBoundaries && current === undefined) {
    return (
      <section className="tile">
        <h3>Мастер главы</h3>
        <p className="tile__note">
          Мастер извлекается только из главы с утверждёнными границами — иначе он был бы снят с
          того, о чём ещё не договорились.{" "}
          <Link href={`/app/books/${bookId}/structure`}>Утвердить границы</Link>
        </p>
      </section>
    );
  }

  return (
    <section className="tile bk-master">
      <div className="tile__head">
        <h3>Мастер главы</h3>
        {current !== undefined && (
          <span className={current.approved_at === null ? "chip chip--warn" : "chip chip--ok"}>
            {current.approved_at === null ? "Не утверждён" : "Утверждён"}
          </span>
        )}
      </div>

      {current === undefined ? (
        <p className="tile__note">
          Мастер — неизменяемый снимок исходного текста главы: блоки получают постоянные коды, и
          текст после этого не правится. Ошибка извлечения исправляется новой версией с причиной.
        </p>
      ) : (
        <>
          <dl className="bk-master__facts">
            <div>
              <dt>Версия</dt>
              <dd>{current.label}</dd>
            </div>
            <div>
              <dt>Блоков</dt>
              <dd>{thousands(current.block_count)}</dd>
            </div>
            <div>
              <dt>Извлечён</dt>
              <dd>{when(current.created_at)}</dd>
            </div>
            <div>
              <dt>Контрольная сумма</dt>
              <dd>
                <CopyId
                  value={current.checksum}
                  title="контрольную сумму мастера"
                  label={shortHash(current.checksum)}
                />
              </dd>
            </div>
            <div>
              <dt>Разбор</dt>
              <dd>{current.parser_version}</dd>
            </div>
          </dl>

          {current.reason !== null && (
            <p className="tile__note">Причина версии {current.label}: {current.reason}</p>
          )}

          {versions.length > 1 && (
            <nav className="bk-versions" aria-label="Версии мастера">
              {versions.map((master) => (
                <Link
                  key={master.id}
                  className={master.id === shownId ? "is-active" : undefined}
                  href={master.id === current.id ? here : `${here}?version=${master.id}`}
                  title={master.reason ?? "первая версия"}
                >
                  {master.label}
                  {master.approved_at !== null && <span aria-label="утверждена"> ✓</span>}
                </Link>
              ))}
            </nav>
          )}
        </>
      )}

      {canManage && approvedBoundaries && (
        <div className="wk-actions">
          {current === undefined && (
            <button
              className="btn btn--primary"
              type="button"
              disabled={pending}
              onClick={() => run(() => extractMaster(bookId, chapterId, null), "Мастер извлечён")}
            >
              Извлечь мастер
            </button>
          )}

          {current !== undefined && current.approved_at === null && (
            <button
              className="btn btn--primary"
              type="button"
              disabled={pending}
              onClick={() =>
                run(() => approveMaster(bookId, chapterId, current.id), "Мастер утверждён")
              }
            >
              Утвердить {current.label}
            </button>
          )}

          {current !== undefined && !asking && (
            <button
              className="btn btn--ghost"
              type="button"
              disabled={pending}
              onClick={() => setAsking(true)}
            >
              Создать новую версию
            </button>
          )}
        </div>
      )}

      {asking && current !== undefined && (
        <form
          className="bk-reason"
          onSubmit={(event) => {
            event.preventDefault();
            const reason = String(new FormData(event.currentTarget).get("reason") ?? "");
            run(() => extractMaster(bookId, chapterId, reason), "Новая версия извлечена");
          }}
        >
          <label className="field">
            <span>Почему нужна новая версия</span>
            <textarea
              name="reason"
              required
              minLength={10}
              maxLength={1000}
              rows={3}
              placeholder="Разборщик терял отступы в листингах кода"
              // Форма открыта нажатием «Создать новую версию» — печатать
              // человек собирался именно здесь.
              autoFocus
            />
            <small>
              Причина остаётся в журнале и в версии: по ней через год объясняют, почему текст
              главы отличается от первого извлечения. Неизменившиеся блоки сохранят коды.
            </small>
          </label>

          <div className="wk-actions">
            <button className="btn btn--primary" type="submit" disabled={pending}>
              {pending ? "Извлекаем…" : `Извлечь v${current.version + 1}`}
            </button>
            <button
              className="btn btn--ghost"
              type="button"
              disabled={pending}
              onClick={() => setAsking(false)}
            >
              Отмена
            </button>
          </div>
        </form>
      )}

      <ReportError error={error} />
    </section>
  );
}
