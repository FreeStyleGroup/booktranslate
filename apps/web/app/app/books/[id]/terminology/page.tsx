import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { currentUser } from "../../../../lib/current-user";
import { organizationId } from "../../../../lib/session";
import {
  load,
  type Book,
  type BookTerminology,
  type GlossaryVersion,
  type TerminologyGate,
} from "../../../../lib/work";
import {
  VERSION_STATUS_CHIP,
  VERSION_STATUS_LABEL,
  plural,
  shortHash,
  thousands,
  when,
} from "../../../labels";
import "../../../work.css";
import "../../../ui/ui.css";
import "../../books.css";
import { CopyId } from "../../../ui/copy-id";
import { DataTable, type Column } from "../../../ui/table";
import { DraftButton } from "./draft-button";

export const metadata: Metadata = {
  title: "Терминология — BookTranslate",
  description: "Версии глоссария книги и готовность каждой главы к переводу.",
};

/* Терминология книги: версии глоссария и гейт каждой главы.

   Перевод опирается на утверждённую версию глоссария — неизменяемый
   снимок словаря, — а не на живой словарь. Здесь собирают черновик,
   смотрят, что держит его утверждение, и видят по каждой главе, открыт ли
   для неё перевод и почему нет. */

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// Кто собирает черновики. Тот же набор, что в API.
const EDITING = new Set(["owner", "admin", "manager", "translator"]);

export default async function TerminologyPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  if (!UUID.test(id)) {
    notFound();
  }

  const here = `/app/books/${id}/terminology`;
  const [book, overview, me, organization] = await Promise.all([
    load<Book>(`/books/${id}`, here),
    load<BookTerminology>(`/books/${id}/terminology`, here),
    currentUser(here),
    organizationId(),
  ]);

  if (book.error !== undefined || overview.error !== undefined) {
    return (
      <section className="tile">
        <h2>Терминология</h2>
        <p className="tile__empty">{book.error ?? overview.error}</p>
        <div className="tile__foot">
          <Link className="btn btn--ghost btn--small" href={`/app/books/${id}`}>
            К книге
          </Link>
        </div>
      </section>
    );
  }

  const membership =
    me?.memberships.find((item) => item.organization_id === organization) ?? me?.memberships[0];
  const canEdit = membership !== undefined && EDITING.has(membership.role);

  const { chapters, versions } = overview.data;
  const codes = new Map(chapters.map((gate) => [gate.chapter_id, gate.chapter_code]));
  const approved = versions.find((item) => item.status === "approved" && item.chapter_id === null);
  const draft = versions.find((item) => item.status === "draft" && item.chapter_id === null);
  const open = chapters.filter((gate) => gate.open).length;
  const versionPath = `${here}/versions`;
  // Предупреждения у глав общие — рабочий словарь у книги один, — и
  // повторять одно и то же по разу на главу незачем.
  const warnings = [
    ...new Map(
      chapters.flatMap((gate) => gate.warnings).map((item) => [item.message, item]),
    ).values(),
  ];

  return (
    <>
      <header className="wk-head">
        <div>
          <p className="wk-crumbs">
            <Link href="/app/books">Книги</Link>
            <span aria-hidden="true"> · </span>
            <Link href={`/app/books/${id}`}>{book.data.title}</Link>
          </p>

          <h1>Терминология</h1>

          <p className="tile__note">
            Перевод главы открыт, когда для неё действует утверждённая версия глоссария, собранная
            по нынешнему тексту главы, и по главе не осталось нерешённых кандидатов.
          </p>
        </div>
      </header>

      <section className="tile">
        <div className="tile__head">
          <h3>Глоссарий книги</h3>
          <span className="tile__note">
            перевод открыт в {thousands(open)} из {thousands(chapters.length)}{" "}
            {plural(chapters.length, "главы", "глав", "глав")}
          </span>
        </div>

        {approved !== undefined ? (
          <p className="bk-version-head">
            <Link href={`${versionPath}/${approved.id}`}>
              <b>Глоссарий {approved.label} утверждён</b>
            </Link>
            {approved.approved_at !== null && (
              <span className="tile__note">{when(approved.approved_at)}</span>
            )}
            <span className="tile__note">{termCount(approved)}</span>
            <CopyId
              value={approved.checksum}
              title="контрольную сумму версии"
              label={shortHash(approved.checksum)}
            />
          </p>
        ) : (
          <p className="tile__note">
            Утверждённой версии для всей книги нет. Соберите черновик: в него войдёт рабочий словарь
            проекта — всё, что решено по кандидатам, загружено и заведено вручную.
          </p>
        )}

        {warnings.length > 0 && (
          <ul className="bk-gate__list bk-gate__list--warn">
            {warnings.map((item) => (
              <li key={item.message}>{item.message}</li>
            ))}
          </ul>
        )}

        {draft !== undefined && (
          <p className="bk-mismatch" role="status">
            <span aria-hidden="true">⚠</span>
            <span>
              Черновик {draft.label} от {when(draft.created_at)} ждёт решения:{" "}
              <Link href={`${versionPath}/${draft.id}`}>открыть</Link>.
            </span>
          </p>
        )}

        {canEdit && (
          <div className="tile__foot">
            <DraftButton
              bookId={id}
              chapterId={null}
              label={draft === undefined ? "Собрать черновик для книги" : "Собрать черновик заново"}
              primary={approved === undefined}
            />
          </div>
        )}
      </section>

      <section className="tile">
        <div className="tile__head">
          <h3>Главы</h3>
        </div>
        <DataTable
          caption="Готовность глав к переводу по терминологии"
          columns={chapterColumns(id, canEdit)}
          rows={chapters.map((gate) => ({ ...gate, id: gate.chapter_id }))}
          empty={
            <>
              У книги ещё нет глав. Сначала разметьте{" "}
              <Link href={`/app/books/${id}/structure`}>структуру книги</Link>.
            </>
          }
        />
      </section>

      <section className="tile">
        <div className="tile__head">
          <h3>Версии</h3>
          <span className="tile__note">новые сверху</span>
        </div>
        <DataTable
          caption="Версии глоссария книги"
          columns={versionColumns(versionPath, codes)}
          rows={versions}
          empty="Версий ещё нет — ни одного черновика не собирали."
        />
      </section>
    </>
  );
}

type GateRow = TerminologyGate & { id: string };

function termCount(version: GlossaryVersion): string {
  if (version.term_count === 0) {
    return "решение: терминов нет";
  }

  return `${thousands(version.term_count)} ${plural(version.term_count, "термин", "термина", "терминов")}`;
}

function chapterColumns(bookId: string, canEdit: boolean): Column<GateRow>[] {
  const chapterPath = (gate: GateRow) => `/app/books/${bookId}/chapters/${gate.chapter_id}`;

  return [
    {
      title: "Глава",
      cell: (gate) => (
        <span className="bk-block-id">
          <Link href={chapterPath(gate)}>{gate.chapter_title ?? `Глава ${gate.ordinal}`}</Link>
          {gate.chapter_code !== null && <span className="tile__note">{gate.chapter_code}</span>}
        </span>
      ),
    },
    {
      title: "Кандидаты",
      // На узком экране то же самое говорит причина в столбце «Перевод».
      secondary: true,
      cell: (gate) => {
        if (gate.master_id === null) {
          return <span className="tile__note">нет мастера</span>;
        }

        if (!gate.collected) {
          return <span className="chip chip--warn">не собраны</span>;
        }

        return gate.undecided > 0 ? (
          <span className="chip chip--warn">без решения: {thousands(gate.undecided)}</span>
        ) : (
          <span className="chip chip--ok">решены</span>
        );
      },
    },
    {
      title: "Действует",
      secondary: true,
      cell: (gate) =>
        gate.version === null ? (
          <span className="tile__note">—</span>
        ) : (
          <span className="tile__note">
            {gate.version.label}
            {gate.version.scope === "chapter" && " · своя"}
          </span>
        ),
    },
    {
      title: "Перевод",
      cell: (gate) => (
        <span className="bk-block-id">
          <span className={gate.open ? "chip chip--ok" : "chip chip--danger"}>
            {gate.open ? "открыт" : "закрыт"}
          </span>
          {gate.blockers[0] !== undefined && (
            <span className="tile__note">{gate.blockers[0].message}</span>
          )}
        </span>
      ),
    },
    {
      title: "Действия",
      cell: (gate) => (
        <span className="bk-tools__side">
          {gate.master_id !== null && (
            <Link className="btn btn--ghost btn--small" href={`${chapterPath(gate)}/terms`}>
              Кандидаты
            </Link>
          )}
          {canEdit && gate.master_id !== null && (
            <DraftButton bookId={bookId} chapterId={gate.chapter_id} label="Версия главы" />
          )}
        </span>
      ),
    },
  ];
}

function versionColumns(
  versionPath: string,
  codes: Map<string, string | null>,
): Column<GlossaryVersion>[] {
  return [
    {
      title: "Версия",
      cell: (version) => <Link href={`${versionPath}/${version.id}`}>{version.label}</Link>,
    },
    {
      title: "Область",
      cell: (version) => (
        <span className="tile__note">
          {version.chapter_id === null
            ? "вся книга"
            : `глава ${codes.get(version.chapter_id) ?? ""}`.trim()}
        </span>
      ),
    },
    {
      title: "Состояние",
      cell: (version) => (
        <span className={VERSION_STATUS_CHIP[version.status] ?? "chip chip--info"}>
          {VERSION_STATUS_LABEL[version.status] ?? version.status}
        </span>
      ),
    },
    {
      title: "Терминов",
      numeric: true,
      cell: (version) => <span className="tile__note">{thousands(version.term_count)}</span>,
    },
    {
      title: "Собрана",
      secondary: true,
      cell: (version) => <span className="tile__note">{when(version.created_at)}</span>,
    },
    {
      title: "Утверждена",
      secondary: true,
      cell: (version) => (
        <span className="tile__note">
          {version.approved_at === null ? "—" : when(version.approved_at)}
        </span>
      ),
    },
  ];
}
