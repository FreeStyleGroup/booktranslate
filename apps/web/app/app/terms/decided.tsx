/* Что по кандидатам уже решено.

   Показывается под разбором, чтобы видеть сделанное и не решать дважды.
   Одинаков для главы и для документа: решение — запись словаря проекта,
   а не свойство того текста, где слово нашлось. */

import Link from "next/link";

import type { TermCandidate } from "../../lib/work";
import { GLOSSARY_KIND, thousands } from "../labels";

export function Decided({ candidates }: { candidates: TermCandidate[] }) {
  const accepted = candidates.filter((item) => item.status === "accepted");
  const rejected = candidates.filter((item) => item.status === "rejected");

  return (
    <section className="tile">
      <div className="tile__head">
        <h3>Уже решено</h3>
        <span className="tile__note">
          принято {thousands(accepted.length)} · отклонено {thousands(rejected.length)}
        </span>
      </div>

      <div className="tm-done">
        {accepted.map((item) => (
          <span className="tm-chip" key={item.id}>
            <b>{item.source_term}</b>
            <i>{GLOSSARY_KIND[item.kind] ?? item.kind}</i>
          </span>
        ))}
        {rejected.map((item) => (
          <span className="tm-chip tm-chip--off" key={item.id}>
            <b>{item.source_term}</b>
            <i>не термин</i>
          </span>
        ))}
      </div>

      <p className="tile__note wk-seg__foot">
        Принятые термины лежат в словаре проекта и применяются ко всем его книгам. Поправить решение
        можно в разделе <Link href="/app/glossary">«Словарь»</Link>.
      </p>
    </section>
  );
}
