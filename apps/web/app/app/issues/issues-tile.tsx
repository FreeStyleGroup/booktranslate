/* Плитка замечаний на странице книги и главы.

   Незакрытая критичная ошибка видна сразу и теми же словами, какими её считает контроль
   выпуска: число приходит из общего счёта API. */

import Link from "next/link";

import type { IssueStats } from "../../lib/work";
import { thousands } from "../labels";

export function IssuesTile({ stats, href, scope }: { stats: IssueStats; href: string; scope: string }) {
  const blocking = stats.open_critical > 0;

  return (
    <section className={blocking ? "tile wk-call bk-gate" : "tile wk-call bk-next"}>
      <div>
        <h3>Реестр ошибок</h3>
        <p>
          {stats.total === 0
            ? `По ${scope} замечаний нет.`
            : `Незакрытых критичных: ${thousands(stats.open_critical)}, серьёзных: ${thousands(stats.open_major)}, всего записей: ${thousands(stats.total)}.`}
          {blocking && " Пока критичные не решены, выпуск будет заблокирован."}
        </p>
      </div>
      <Link className="btn btn--ghost btn--small" href={href}>
        Открыть
      </Link>
    </section>
  );
}
