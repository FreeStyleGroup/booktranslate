"use client";

/* Финальная версия главы: что мешает её создать, сами версии и читательская выгрузка.

   Кнопка активна только при пустом списке причин. Сервер проверит то же самое ещё раз: между показом
   и нажатием всё могло измениться. После утверждения версия не меняется, и правка рабочего текста её
   не задевает: это видно пометкой «рабочий текст новее». */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import type { ChapterRelease, ReleaseGate } from "../../../../../lib/work";
import { plural, shortHash, thousands, when } from "../../../../labels";
import { CopyId } from "../../../../ui/copy-id";
import { ReportError, useToast } from "../../../../ui/toast";
import { ExportLinks } from "../../../export-links";
import {
  approveChapterRelease,
  createChapterRelease,
  discardChapterRelease,
  type ReleaseResult,
} from "../../../release-actions";

export function ReleasePanel({
  bookId,
  chapterId,
  gate,
  releases,
  canCreate,
  canApprove,
}: {
  bookId: string;
  chapterId: string;
  gate: ReleaseGate;
  releases: ChapterRelease[];
  canCreate: boolean;
  canApprove: boolean;
}) {
  const [major, setMajor] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const router = useRouter();
  const toast = useToast();

  const draft = releases.find((item) => item.status === "draft");
  const hasApproved = releases.some((item) => item.status === "approved");
  const latestApproved = releases.find((item) => item.status === "approved");
  // Текст не менялся с последней версии: новая была бы той же самой.
  const upToDate = releases[0] !== undefined && !releases[0].working_differs;
  const here = `/app/books/${bookId}/chapters/${chapterId}`;

  function run(action: () => Promise<ReleaseResult>, done: (result: ReleaseResult) => string): void {
    setError(null);

    start(async () => {
      const result = await action();

      if (result.error !== undefined) {
        setError(result.error);
        router.refresh();
        return;
      }

      toast.ok(done(result));
      router.refresh();
    });
  }

  return (
    <section className={gate.ready ? "tile bk-gate is-open" : "tile bk-gate"}>
      <div className="tile__head">
        <h3>Финальная версия главы</h3>
        {upToDate ? (
          <span className="chip chip--ok">версия актуальна</span>
        ) : (
          <span className={gate.ready ? "chip chip--ok" : "chip chip--danger"}>
            {gate.ready ? "можно создать" : `причин: ${thousands(gate.blockers.length)}`}
          </span>
        )}
      </div>

      {gate.blockers.length > 0 && (
        <ul className="bk-gate__list">
          {gate.blockers.map((item) => (
            <li key={item.code}>{item.message}</li>
          ))}
        </ul>
      )}

      {canCreate && draft === undefined && !upToDate && (
        <div className="wk-actions">
          <button
            className="btn btn--primary"
            type="button"
            disabled={pending || !gate.ready}
            title={gate.ready ? undefined : "Сначала снимите причины выше"}
            onClick={() =>
              run(
                () => createChapterRelease(bookId, chapterId, major),
                (result) => `Создана ${result.code}: теперь её нужно утвердить`,
              )
            }
          >
            Создать финальную версию главы
          </button>

          {hasApproved && (
            <label className="bk-check-inline">
              <input
                type="checkbox"
                checked={major}
                onChange={(event) => setMajor(event.target.checked)}
              />
              <span>Новая старшая версия</span>
            </label>
          )}
        </div>
      )}

      {releases.length > 0 && (
        <ul className="bk-releases">
          {releases.map((item) => (
            <li key={item.id}>
              <div className="bk-releases__head">
                <CopyId value={item.code} title="код версии" />
                <span className={item.status === "approved" ? "chip chip--ok" : "chip chip--warn"}>
                  {item.status === "approved" ? "утверждена" : "не утверждена"}
                </span>
                {item.working_differs && (
                  <span className="chip chip--warn">рабочий текст новее</span>
                )}
              </div>

              <p className="tile__note">
                {thousands(item.blocks)} {plural(item.blocks, "блок", "блока", "блоков")},{" "}
                {thousands(item.objects)} {plural(item.objects, "объект", "объекта", "объектов")} ·
                сумма{" "}
                {shortHash(item.manifest_hash)}
                {item.creator !== null && ` · автор ${item.creator}`}
                {item.approved_at !== null &&
                  ` · утверждена ${when(item.approved_at)}${item.approver !== null ? `, ${item.approver}` : ""}`}
              </p>

              <div className="wk-actions">
                {item.status === "draft" && canApprove && (
                  <button
                    className="btn btn--primary btn--small"
                    type="button"
                    disabled={pending}
                    onClick={() =>
                      run(
                        () => approveChapterRelease(bookId, chapterId, item.id),
                        () => `${item.code} утверждена: теперь она не меняется`,
                      )
                    }
                  >
                    Утвердить
                  </button>
                )}
                {item.status === "draft" && canCreate && (
                  <button
                    className="btn btn--ghost btn--small"
                    type="button"
                    disabled={pending}
                    onClick={() =>
                      run(
                        () => discardChapterRelease(bookId, chapterId, item.id),
                        () => `${item.code} отменена`,
                      )
                    }
                  >
                    Отменить
                  </button>
                )}
                {item.working_differs && (
                  <Link
                    className="btn btn--ghost btn--small"
                    href={`${here}/releases/${item.id}`}
                  >
                    Что изменилось с этой версии
                  </Link>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      {latestApproved !== undefined && (
        <>
          <h4 className="is-subhead">Читательская версия {latestApproved.code}</h4>
          <p className="tile__note">
            Только содержание книги: без кодов, замечаний и заметок. Файл проверяется перед выдачей.
          </p>
          <ExportLinks
            path={`/api/chapter-releases/${latestApproved.id}/export`}
            formats={["docx", "markdown", "text"]}
            draft={false}
          />
        </>
      )}

      <ReportError error={error} />
    </section>
  );
}
