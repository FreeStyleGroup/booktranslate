"use client";

/* Спросить справки.

   По слову на строку: список приходит из головы переводчика или из
   кандидатов книги, и вводить его по одному — значит не спросить вовсе.
   Отрывок и отрасль не обязательны, но без них «head» — это и «головка»,
   и «оголовок».

   Итог — числа, а не только список: сколько досталось из каталога
   бесплатно и во что обошлось спрошенное заново. Ради этого каталог и
   заведён, и по этим числам видно, окупается ли он. */

import { useActionState } from "react";

import type { CatalogSource } from "../../lib/work";
import { plural, thousands } from "../labels";
import { lookupTerms, type LookupResult } from "./actions";

const EMPTY: LookupResult = {};

export type Pair = { value: string; source: string; target: string };

export function LookupForm({ pairs, source }: { pairs: Pair[]; source: CatalogSource | null }) {
  const [state, action, busy] = useActionState(lookupTerms, EMPTY);

  return (
    <section className="tile ct-block">
      <div className="tile__head">
        <h3>Спросить про слова</h3>
        <span className="tile__note">по одному на строку</span>
      </div>

      {source !== null && !source.online && (
        <p className="ct-offline">
          Внешний источник выключен на сервере: справочник ответит «не нашёл» на всё, что не лежит в
          каталоге. Включается переменной <code>TERM_LOOKUP_PROVIDER=claude</code>.
        </p>
      )}

      <form key={state.at ?? 0} action={action} className="ct-form">
        <label className="field ct-form__terms">
          <span>Слова</span>
          <textarea name="terms" required rows={4} placeholder={"basis risk\nslippage\nPLC"} />
        </label>

        <label className="field">
          <span>Пара</span>
          <select name="pair" defaultValue={pairs[0]?.value}>
            {pairs.map((pair) => (
              <option key={pair.value} value={pair.value}>
                {pair.source} → {pair.target}
              </option>
            ))}
          </select>
        </label>

        <label className="field">
          <span>Отрасль</span>
          <input name="subject" maxLength={300} placeholder="Насосы, финансы, право" />
        </label>

        <label className="field ct-form__sample">
          <span>Отрывок, где встретилось</span>
          <input
            name="sample"
            maxLength={1000}
            placeholder="Необязательно, но снимает двусмысленность"
          />
        </label>

        <label className="ct-check">
          <input name="refresh" type="checkbox" value="yes" />
          <span>
            Спросить заново и то, что уже есть в каталоге
            <small>Например, когда справку получили до того, как стала ясна отрасль.</small>
          </span>
        </label>

        <button className="btn btn--primary" type="submit" disabled={busy}>
          {busy ? "Спрашиваем…" : "Спросить"}
        </button>
      </form>

      {state.error !== undefined && (
        <p className="form__error" role="alert">
          {state.error}
        </p>
      )}

      {state.report !== undefined && state.error === undefined && (
        <p className="wk-note" role="status">
          <span aria-hidden="true">✅</span>
          <span>
            Из каталога бесплатно: <b>{thousands(state.report.from_catalog)}</b>, спрошено заново:{" "}
            <b>{thousands(state.report.asked)}</b>, найдено: <b>{thousands(state.report.found)}</b>
            {state.report.searches > 0 &&
              ` · ${thousands(state.report.searches)} ${plural(state.report.searches, "поисковый запрос", "поисковых запроса", "поисковых запросов")}`}
            {state.report.estimated_usd !== null &&
              ` · ≈ $${state.report.estimated_usd.toFixed(3)}`}
            . Справки ниже, в каталоге.
          </span>
        </p>
      )}
    </section>
  );
}
