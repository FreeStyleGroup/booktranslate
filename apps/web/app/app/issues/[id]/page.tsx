import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { load, type IssueDetail, type IssueEvent } from "../../../lib/work";
import {
  ISSUE_CATEGORY_LABEL,
  ISSUE_EVENT_LABEL,
  ISSUE_SEVERITY_CHIP,
  ISSUE_SEVERITY_LABEL,
  ISSUE_STATUS_CHIP,
  ISSUE_STATUS_LABEL,
  OBJECT_ONE,
  fileSize,
  plural,
  thousands,
  when,
} from "../../labels";
import "../../work.css";
import "../../ui/ui.css";
import "../../books/books.css";
import "../issues.css";
import { CopyId } from "../../ui/copy-id";
import { AttachFile } from "../attach-file";
import { IssueActions } from "../issue-actions";

export const metadata: Metadata = {
  title: "Замечание — BookTranslate",
  description: "Что найдено, оригинал, контекст, предложенное исправление и лента решений.",
};

/* Карточка замечания. Здесь же идёт проверка: что обнаружено, оригинал, контекст и предложение.

   Снимки показывают, как было на момент находки, и не меняются. Текущий текст стоит рядом
   отдельно: сравнивать надо именно их. */

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function statusLine(event: IssueEvent): string {
  if (event.kind === "status_changed" && event.to_status !== null) {
    return event.from_status !== null
      ? `${ISSUE_STATUS_LABEL[event.from_status]} → ${ISSUE_STATUS_LABEL[event.to_status]}`
      : ISSUE_STATUS_LABEL[event.to_status];
  }

  return ISSUE_EVENT_LABEL[event.kind];
}

function changeLine(event: IssueEvent): string | null {
  if (event.kind !== "reclassified") {
    return null;
  }

  const parts: string[] = [];
  const category = event.payload.category as [string, string] | undefined;
  const severity = event.payload.severity as [string, string] | undefined;

  if (category !== undefined) {
    parts.push(
      `категория: ${ISSUE_CATEGORY_LABEL[category[0] as never] ?? category[0]} → ${ISSUE_CATEGORY_LABEL[category[1] as never] ?? category[1]}`,
    );
  }

  if (severity !== undefined) {
    parts.push(
      `серьёзность: ${ISSUE_SEVERITY_LABEL[severity[0] as never] ?? severity[0]} → ${ISSUE_SEVERITY_LABEL[severity[1] as never] ?? severity[1]}`,
    );
  }

  return parts.join(", ");
}

type Team = { members: { user_id: string; email: string }[] };

export default async function IssuePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  if (!UUID.test(id)) {
    notFound();
  }

  const here = `/app/issues/${id}`;
  const [found, team] = await Promise.all([
    load<IssueDetail>(`/issues/${id}`, here),
    load<Team>("/team", here),
  ]);

  if (found.error !== undefined) {
    return (
      <section className="tile">
        <h2>Замечание</h2>
        <p className="tile__empty">{found.error}</p>
        <div className="tile__foot">
          <Link className="btn btn--ghost btn--small" href="/app/issues">
            К реестру
          </Link>
        </div>
      </section>
    );
  }

  const issue = found.data;
  const chapterPath = `/app/books/${issue.book_id}/chapters/${issue.chapter_id}`;
  const changed =
    issue.current_text !== null &&
    issue.target_snapshot !== null &&
    issue.current_text !== issue.target_snapshot;
  // Текст объекта собран из нескольких блоков: сравнение снимка с одной редакцией ввело бы в
  // заблуждение, поэтому текущий текст показывается только для блока.
  const showsCurrent = issue.block_id !== null;

  return (
    <>
      <header className="wk-head">
        <div>
          <p className="wk-crumbs">
            <Link href="/app/issues">Реестр ошибок</Link>
            <span aria-hidden="true"> · </span>
            <Link href={`/app/books/${issue.book_id}`}>{issue.book_title}</Link>
            <span aria-hidden="true"> · </span>
            <Link href={chapterPath}>{issue.chapter_label ?? "Глава"}</Link>
          </p>
          <h1>Замечание: {ISSUE_CATEGORY_LABEL[issue.category].toLowerCase()}</h1>
          <p className="tile__note">
            {issue.automatic ? "нашла проверка" : `нашёл ${issue.detected_by ?? "удалённый участник"}`}{" "}
            · {when(issue.created_at)}
            {issue.assignee !== null && ` · поручено ${issue.assignee}`}
            {` · вес ${thousands(issue.priority_score)}`}
            {issue.impact_count > 1 &&
              ` · такой текст встречается ${thousands(issue.impact_count)} ${plural(issue.impact_count, "раз", "раза", "раз")}`}
          </p>
        </div>

        <div className="bk-head__side">
          <CopyId value={issue.code} title="код ошибки" />
          <span className={ISSUE_SEVERITY_CHIP[issue.severity]}>
            {ISSUE_SEVERITY_LABEL[issue.severity]}
          </span>
          <span className={ISSUE_STATUS_CHIP[issue.status]}>{ISSUE_STATUS_LABEL[issue.status]}</span>
          {issue.archived_at !== null && <span className="chip chip--info">в архиве</span>}
        </div>
      </header>

      {!issue.subject_active && (
        <p className="bk-mismatch" role="status">
          <span aria-hidden="true">⚠</span>
          <span>Этого текста нет в текущей версии мастера: снимок остался от прежней.</span>
        </p>
      )}

      <section className="tile">
        <div className="tile__head">
          <h3>Что обнаружено</h3>
          <span className="tile__note">
            {issue.block_id !== null && (
              <Link href={`${chapterPath}/translation/${issue.block_id}`}>{issue.block_code}</Link>
            )}
            {issue.block_id === null && issue.object_id !== null && (
              <Link href={`${chapterPath}/objects/${issue.object_id}`}>{issue.object_code}</Link>
            )}
          </span>
        </div>

        <p className="bk-block-text">{issue.description}</p>

        {issue.proposed_fix !== null && (
          <>
            <h4 className="is-subhead">Предложенное исправление</h4>
            <p className="bk-block-text">{issue.proposed_fix}</p>
          </>
        )}
      </section>

      <section className="tile">
        <div className="tile__head">
          <h3>Текст на момент находки</h3>
          <span className="tile__note">снимок не меняется</span>
        </div>

        <div className="is-pair">
          <div>
            <h4>Оригинал</h4>
            <p className="bk-block-text">{issue.source_snapshot}</p>
          </div>
          <div>
            <h4>Перевод</h4>
            {issue.target_snapshot === null ? (
              <p className="tile__note">Перевода тогда ещё не было.</p>
            ) : (
              <p className="bk-block-text">{issue.target_snapshot}</p>
            )}
          </div>
        </div>

        {showsCurrent && changed && (
          <>
            <h4 className="is-subhead">Текущий перевод</h4>
            <p className="bk-block-text">{issue.current_text}</p>
          </>
        )}
        {showsCurrent && !changed && issue.current_text !== null && (
          <p className="tile__note">Текст с тех пор не менялся.</p>
        )}
      </section>

      <IssueActions issue={issue} members={team.data?.members ?? []} />

      {issue.context.length > 0 && (
        <section className="tile">
          <div className="tile__head">
            <h3>Контекст</h3>
            <span className="tile__note">соседние блоки главы, как сейчас</span>
          </div>
          <ul className="is-context">
            {issue.context.map((item) => (
              <li key={item.block_id}>
                <span className="tile__note is-context__code">{item.code}</span>
                <span className="bk-block-text">{item.source_text}</span>
                <span className="bk-block-text">{item.translation ?? "—"}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {issue.terms.length > 0 && (
        <section className="tile">
          <div className="tile__head">
            <h3>Термины в этом тексте</h3>
            <span className="tile__note">из действующей версии глоссария</span>
          </div>
          <ul className="is-terms">
            {issue.terms.map((term) => (
              <li key={term.source}>
                <b>{term.source}</b> — {term.target}
                {term.mandatory && <span className="tile__note"> · обязательный</span>}
                {term.note !== null && <span className="tile__note"> · {term.note}</span>}
              </li>
            ))}
          </ul>
        </section>
      )}

      {(issue.objects.length > 0 || issue.parent !== null || issue.children.length > 0) && (
        <section className="tile">
          <div className="tile__head">
            <h3>Связи</h3>
          </div>
          <ul className="is-terms">
            {issue.objects.map((item) => (
              <li key={item.id}>
                {OBJECT_ONE[item.type] ?? item.type}:{" "}
                <Link href={`${chapterPath}/objects/${item.id}`}>{item.code}</Link>
              </li>
            ))}
            {issue.parent !== null && (
              <li>
                Выросло из: <Link href={`/app/issues/${issue.parent.id}`}>{issue.parent.code}</Link>
                {" · "}
                {ISSUE_STATUS_LABEL[issue.parent.status]}
              </li>
            )}
            {issue.children.map((child) => (
              <li key={child.id}>
                Дочернее: <Link href={`/app/issues/${child.id}`}>{child.code}</Link>
                {" · "}
                {ISSUE_STATUS_LABEL[child.status]}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="tile">
        <div className="tile__head">
          <h3>Вложения</h3>
        </div>

        {issue.attachments.length > 0 && (
          <ul className="is-files">
            {issue.attachments.map((file) => {
              const path = `/api/issues/${issue.id}/attachments/${file.id}`;

              return (
                <li key={file.id}>
                  {file.media_type.startsWith("image/") && (
                    // Снимок лежит за токеном и проходит через витрину: оптимизатор
                    // изображений его не получит, и размеры заранее неизвестны.
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={path} alt={`Вложение: ${file.filename}`} loading="lazy" />
                  )}
                  <a className="tile__note" href={path} target="_blank" rel="noreferrer">
                    {file.filename} · {fileSize(file.size_bytes)}
                  </a>
                </li>
              );
            })}
          </ul>
        )}

        {issue.actions.includes("comment") ? (
          <AttachFile issueId={issue.id} />
        ) : (
          issue.attachments.length === 0 && <p className="tile__empty">Вложений нет.</p>
        )}
      </section>

      <section className="tile">
        <div className="tile__head">
          <h3>Лента</h3>
          <span className="tile__note">кто и когда решал</span>
        </div>

        <ol className="is-timeline">
          {issue.events.map((event) => (
            <li key={event.id}>
              <b>{statusLine(event)}</b>
              <span className="tile__note">
                {event.actor ?? "система"} · {when(event.created_at)}
              </span>
              {changeLine(event) !== null && <p>{changeLine(event)}</p>}
              {event.note !== null && <p>{event.note}</p>}
            </li>
          ))}
        </ol>
      </section>
    </>
  );
}
