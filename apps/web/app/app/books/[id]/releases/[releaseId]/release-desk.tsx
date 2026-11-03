"use client";

/* Чек-лист, файлы и постраничный аудит выпуска.

   Подтверждение необратимо: после него выпуск, файлы и аудит не меняются. Поэтому кнопка переспросит,
   а сервер всё равно проверяет заново. Причина ведёт туда, где её снимают: на замечание, на страницу
   или на главу. */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, useTransition } from "react";

import type {
  BookRelease,
  IssueSeverity,
  PageAudit,
  ReleaseArtifact,
  ReleaseControl,
  ReleaseFiles,
} from "../../../../../lib/work";
import {
  ISSUE_SEVERITY_HINT,
  ISSUE_SEVERITY_LABEL,
  ISSUE_SEVERITY_ORDER,
  fileSize,
  plural,
  shortHash,
  thousands,
  when,
} from "../../../../labels";
import { ReportError, useToast } from "../../../../ui/toast";
import {
  passPage,
  passRelease,
  registerPageIssue,
  renderRelease,
  type ReleaseResult,
} from "../../../release-actions";

const POLL_MS = 4000;

const PAGE_LABEL: Record<PageAudit["status"], string> = {
  unreviewed: "не проверена",
  pass: "верна",
  issue: "с ошибкой",
  stale: "устарела",
};

function useAct(): {
  pending: boolean;
  error: string | null;
  act: (action: () => Promise<ReleaseResult>, done: () => void) => void;
} {
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const router = useRouter();

  function act(action: () => Promise<ReleaseResult>, done: () => void): void {
    setError(null);

    start(async () => {
      const result = await action();

      if (result.error !== undefined) {
        setError(result.error);
        router.refresh();
        return;
      }

      done();
    });
  }

  return { pending, error, act };
}

export function GatePanel({
  bookId,
  release,
  gate,
  canPass,
}: {
  bookId: string;
  release: BookRelease;
  gate: ReleaseControl;
  canPass: boolean;
}) {
  const [asking, setAsking] = useState(false);
  const { pending, error, act } = useAct();
  const router = useRouter();
  const toast = useToast();
  const passed = gate.status === "passed";
  const here = `/app/books/${bookId}/releases/${release.id}`;

  return (
    <section className={gate.ready || passed ? "tile bk-gate is-open" : "tile bk-gate"}>
      <div className="tile__head">
        <h3>Чек-лист</h3>
        {passed ? (
          <span className="chip chip--ok">выпуск подтверждён</span>
        ) : (
          <span className={gate.ready ? "chip chip--ok" : "chip chip--danger"}>
            {gate.ready ? "можно выпускать" : `мешает: ${thousands(gate.blockers.length)}`}
          </span>
        )}
      </div>

      {passed && gate.passed_at !== null && (
        <p className="tile__note">
          Контроль пройден {when(gate.passed_at)}. Выпуск, файлы и аудит больше не меняются. Сумма
          манифеста {shortHash(release.manifest_hash)}.
        </p>
      )}

      <ul className="bk-checklist">
        {gate.checks.map((item) => (
          <li
            key={item.code}
            className={item.passed ? "is-ok" : "is-bad"}
            aria-label={`${item.title}: ${item.passed ? "выполнено" : "не выполнено"}`}
          >
            <span aria-hidden="true">{item.passed ? "✓" : "✕"}</span>
            <span>{item.title}</span>
          </li>
        ))}
      </ul>

      {gate.blockers.length > 0 && !passed && (
        <ul className="bk-gate__list">
          {gate.blockers.map((item, index) => (
            <li key={`${item.code}-${index}`}>
              {item.issue_id !== null ? (
                <Link href={`/app/issues/${item.issue_id}`}>{item.message}</Link>
              ) : item.page_no !== null ? (
                <Link href={`${here}?page=${item.page_no}`} prefetch={false}>
                  {item.message}
                </Link>
              ) : item.chapter_id !== null ? (
                <Link href={`/app/books/${bookId}/chapters/${item.chapter_id}`}>{item.message}</Link>
              ) : (
                item.message
              )}
            </li>
          ))}
        </ul>
      )}

      {canPass && !passed && !asking && (
        <div className="wk-actions">
          <button
            className="btn btn--primary"
            type="button"
            disabled={!gate.ready}
            title={gate.ready ? undefined : "Сначала снимите причины выше"}
            onClick={() => setAsking(true)}
          >
            Подтвердить выпуск
          </button>
        </div>
      )}

      {asking && !passed && (
        <div className="bk-mismatch" role="alert">
          <span aria-hidden="true">⚠</span>
          <div>
            <p>
              После подтверждения выпуск {release.code}, его файлы и аудит больше не изменятся.
              Исправление потребует нового выпуска.
            </p>
            <div className="wk-actions">
              <button
                className="btn btn--primary"
                type="button"
                disabled={pending}
                onClick={() =>
                  act(
                    () => passRelease(bookId, release.id),
                    () => {
                      toast.ok(`${release.code}: контроль пройден`);
                      setAsking(false);
                      router.refresh();
                    },
                  )
                }
              >
                {pending ? "Проверяем…" : "Да, подтвердить выпуск"}
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
          </div>
        </div>
      )}

      <ReportError error={error} />
    </section>
  );
}

function Artifact({ item }: { item: ReleaseArtifact }) {
  return (
    <li>
      <div className="bk-releases__head">
        <b>{item.format.toUpperCase()}</b>
        <span className="tile__note">
          {fileSize(item.size)}
          {item.page_count !== null &&
            ` · ${thousands(item.page_count)} ${plural(item.page_count, "страница", "страницы", "страниц")}`}
          {` · сумма ${shortHash(item.checksum)} · ${when(item.created_at)}`}
        </span>
      </div>
      <div className="wk-actions">
        <a
          className="btn btn--ghost btn--small"
          href={`/api/artifacts/${item.id}/download`}
          download
        >
          Скачать
        </a>
      </div>
    </li>
  );
}

export function FilesPanel({
  bookId,
  release,
  files,
  canRender,
}: {
  bookId: string;
  release: BookRelease;
  files: ReleaseFiles;
  canRender: boolean;
}) {
  const { pending, error, act } = useAct();
  const router = useRouter();
  const toast = useToast();
  const running = files.job_state === "waiting" || files.job_state === "running";

  useEffect(() => {
    if (!running) {
      return;
    }

    const timer = window.setInterval(() => router.refresh(), POLL_MS);

    return () => window.clearInterval(timer);
  }, [running, router]);

  return (
    <section className="tile">
      <div className="tile__head">
        <h3>Файлы</h3>
        {running && (
          <span className="chip chip--info">
            {files.job_state === "waiting" ? "в очереди" : "собирается"}
          </span>
        )}
      </div>

      <p className="tile__note">
        DOCX и PDF собираются из одного манифеста, у каждого своя сумма. Новая сборка заменяет файлы, а
        аудит прежнего PDF перестаёт действовать.
      </p>

      {files.job_state === "failed" && files.job_error !== null && (
        <p className="bk-mismatch" role="status">
          <span aria-hidden="true">⚠</span>
          <span>Сборка сорвалась: {files.job_error}</span>
        </p>
      )}

      {files.artifacts.length > 0 ? (
        <ul className="bk-releases">
          {files.artifacts.map((item) => (
            <Artifact key={item.id} item={item} />
          ))}
        </ul>
      ) : (
        !running && <p className="tile__empty">Файлы ещё не собраны.</p>
      )}

      {canRender && release.status !== "passed" && !running && (
        <div className="wk-actions">
          <button
            className={files.artifacts.length === 0 ? "btn btn--primary" : "btn btn--ghost"}
            type="button"
            disabled={pending}
            onClick={() =>
              act(
                () => renderRelease(bookId, release.id),
                () => {
                  toast.ok("Сборка поставлена в очередь");
                  router.refresh();
                },
              )
            }
          >
            {files.artifacts.length === 0 ? "Собрать файлы" : "Собрать заново"}
          </button>
        </div>
      )}

      {files.previous.length > 0 && (
        <details className="bk-raw">
          <summary>Прежние сборки: {thousands(files.previous.length)}</summary>
          <ul className="bk-review__list">
            {files.previous.map((item) => (
              <li key={item.id} className="tile__note">
                {item.format.toUpperCase()} · сумма {shortHash(item.checksum)} ·{" "}
                {when(item.created_at)}
              </li>
            ))}
          </ul>
        </details>
      )}

      <ReportError error={error} />
    </section>
  );
}

export function PageAuditPanel({
  bookId,
  releaseId,
  artifact,
  pages,
  pageNo,
  canAudit,
  here,
}: {
  bookId: string;
  releaseId: string;
  artifact: ReleaseArtifact;
  pages: PageAudit[];
  pageNo: number;
  canAudit: boolean;
  here: string;
}) {
  const [asking, setAsking] = useState(false);
  const [severity, setSeverity] = useState<IssueSeverity>("major");
  const { pending, error, act } = useAct();
  const router = useRouter();
  const toast = useToast();

  const current = pages.find((item) => item.page_no === pageNo);
  const waiting = pages.filter((item) => item.status === "unreviewed");
  const done = pages.filter((item) => item.status === "pass").length;
  const next =
    waiting.find((item) => item.page_no > pageNo)?.page_no ??
    waiting.find((item) => item.page_no !== pageNo)?.page_no ??
    null;

  function go(page: number | null): void {
    router.push(page === null ? here : `${here}?page=${page}`);
    router.refresh();
  }

  return (
    <section className="tile">
      <div className="tile__head">
        <h3>Аудит страниц PDF</h3>
        <span className={done === pages.length ? "chip chip--ok" : "chip chip--info"}>
          {thousands(done)} из {thousands(pages.length)}
        </span>
      </div>

      <nav className="bk-pages" aria-label="Страницы PDF">
        {pages.map((item) => (
          <Link
            key={item.page_no}
            href={`${here}?page=${item.page_no}`}
            prefetch={false}
            className={`is-${item.status}${item.page_no === pageNo ? " is-current" : ""}`}
            aria-current={item.page_no === pageNo ? "page" : undefined}
            title={`Страница ${item.page_no}: ${PAGE_LABEL[item.status]}`}
          >
            {item.page_no}
          </Link>
        ))}
      </nav>

      <div className="wk-actions">
        {canAudit && current?.status !== "pass" && !asking && (
          <button
            className="btn btn--primary"
            type="button"
            disabled={pending}
            onClick={() =>
              act(
                () => passPage(bookId, releaseId, artifact.id, pageNo),
                () => go(next),
              )
            }
          >
            Страница верна{next !== null ? ", дальше" : ""}
          </button>
        )}
        {next !== null && (
          <Link className="btn btn--ghost" href={`${here}?page=${next}`} prefetch={false}>
            Следующая непроверенная
          </Link>
        )}
        {canAudit && current?.status !== "issue" && !asking && (
          <button className="btn btn--ghost" type="button" onClick={() => setAsking(true)}>
            Есть ошибка вёрстки
          </button>
        )}
        {current?.issue_id !== null && current?.issue_id !== undefined && (
          <Link className="btn btn--ghost" href={`/app/issues/${current.issue_id}`}>
            Открыть замечание
          </Link>
        )}
      </div>

      {asking && (
        <form
          className="is-form"
          onSubmit={(event) => {
            event.preventDefault();
            const description = String(new FormData(event.currentTarget).get("description") ?? "");

            act(
              () => registerPageIssue(bookId, releaseId, artifact.id, pageNo, severity, description),
              () => {
                toast.ok(`Страница ${pageNo}: замечание заведено, снимок приложен`);
                setAsking(false);
                router.refresh();
              },
            );
          }}
        >
          <label className="field">
            <span>Серьёзность</span>
            <select
              value={severity}
              onChange={(event) => setSeverity(event.target.value as IssueSeverity)}
            >
              {ISSUE_SEVERITY_ORDER.map((value) => (
                <option key={value} value={value}>
                  {ISSUE_SEVERITY_LABEL[value]}
                </option>
              ))}
            </select>
            <small>{ISSUE_SEVERITY_HINT[severity]}</small>
          </label>
          <label className="field">
            <span>Что не так на странице {pageNo}</span>
            <textarea name="description" required maxLength={10000} rows={3} autoFocus />
          </label>
          <div className="wk-actions">
            <button className="btn btn--primary" type="submit" disabled={pending}>
              {pending ? "Записываем…" : "Завести замечание"}
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

      <figure className="bk-page">
        {/* Картинку отдаёт маршрут витрины по сеансу: оптимизатору изображений её не получить. */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={`/api/artifacts/${artifact.id}/pages/${pageNo}`}
          alt={`Страница ${pageNo} файла PDF`}
        />
        <figcaption className="tile__note">
          Страница {pageNo} из {thousands(pages.length)}
          {current !== undefined && ` · ${PAGE_LABEL[current.status]}`}
        </figcaption>
      </figure>
    </section>
  );
}
