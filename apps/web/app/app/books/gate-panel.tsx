/* Гейт терминологии главы: можно ли её переводить с точки зрения терминов.

   Ответ — до кнопки «Перевести»: «Глоссарий v3 утверждён» зелёным либо
   причины, которые держат главу, словами API. Предупреждения — отдельно:
   они не держат, но о них надо знать, например о правках словаря после
   утверждения. */

import Link from "next/link";

import type { TerminologyGate } from "../../lib/work";
import { plural, thousands, when } from "../labels";

export function GatePanel({
  gate,
  bookId,
  termsLink,
}: {
  gate: TerminologyGate;
  bookId: string;
  /** Показывать ли ссылку на кандидатов главы — не нужна на их же экране. */
  termsLink: boolean;
}) {
  const version = gate.version;
  const chapterPath = `/app/books/${bookId}/chapters/${gate.chapter_id}`;

  return (
    <section className={gate.open ? "tile bk-gate is-open" : "tile bk-gate"}>
      <div className="tile__head">
        <h3>Терминология</h3>
        <span className={gate.open ? "chip chip--ok" : "chip chip--danger"}>
          {gate.open ? "перевод открыт" : "перевод закрыт"}
        </span>
      </div>

      {version !== null ? (
        <p className="bk-gate__version">
          <b>Глоссарий {version.label} утверждён</b>
          {version.approved_at !== null && ` ${when(version.approved_at)}`}
          {" · "}
          {version.term_count === 0
            ? "решение: терминов нет"
            : `${thousands(version.term_count)} ${plural(version.term_count, "термин", "термина", "терминов")}`}
          {version.scope === "chapter" && " · своя версия главы"}
        </p>
      ) : (
        <p className="tile__note">Утверждённой версии глоссария для этой главы нет.</p>
      )}

      {gate.blockers.length > 0 && (
        <ul className="bk-gate__list">
          {gate.blockers.map((item, index) => (
            <li key={`${item.code}-${index}`}>{item.message}</li>
          ))}
        </ul>
      )}

      {gate.warnings.length > 0 && (
        <ul className="bk-gate__list bk-gate__list--warn">
          {gate.warnings.map((item, index) => (
            <li key={`${item.code}-${index}`}>{item.message}</li>
          ))}
        </ul>
      )}

      <div className="tile__foot">
        {termsLink && (
          <Link className="btn btn--ghost btn--small" href={`${chapterPath}/terms`}>
            Термины главы
          </Link>
        )}
        <Link className="btn btn--ghost btn--small" href={`/app/books/${bookId}/terminology`}>
          Терминология книги
        </Link>
      </div>
    </section>
  );
}
