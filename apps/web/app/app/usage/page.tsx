import type { Metadata } from "next";
import Link from "next/link";

import { load } from "../../lib/work";
import { plural, thousands } from "../labels";
import "../work.css";
import "./usage.css";
import { Legend, Months, Share, colorFor, type Part } from "./charts";

export const metadata: Metadata = {
  title: "Расход — BookTranslate",
  description: "Во что обошёлся перевод: по месяцам, моделям и книгам.",
};

/* Расход рабочего пространства.

   Отвечает на три вопроса, и разложен ровно по ним: сколько всего, когда
   тратили и на что. Четвёртый — «какой моделью» — не отдельный вопрос, а
   разрез первых трёх: смена модели меняет счёт сильнее, чем объём работы,
   и свалить всё в одну кучу значит спрятать главную причину.

   Токены хранятся, деньги считаются на лету. Поэтому суммы здесь всегда
   помечены как оценка: сторона поставщика считает по-своему — пробные
   периоды, скидки за объём, разные ставки у облачных площадок. */

type Tokens = {
  input_tokens: number;
  output_tokens: number;
  cached_input_tokens: number;
  cache_write_tokens: number;
};

type Money = { tokens: Tokens; usd: number | null };
type ModelSpend = { model: string; documents: number; money: Money };

type UsageReport = {
  total: Money;
  documents: number;
  by_month: { month: string; money: Money; by_model: ModelSpend[] }[];
  by_model: ModelSpend[];
  by_document: {
    document_id: string;
    title: string;
    project_name: string;
    translated_by: string | null;
    money: Money;
  }[];
};

/** Всего токенов в строке расхода. Кэш входит: он тоже оплачен, просто
 *  дешевле, и выкидывать его из «сколько потрачено» нельзя. */
function all(tokens: Tokens): number {
  return (
    tokens.input_tokens +
    tokens.output_tokens +
    tokens.cached_input_tokens +
    tokens.cache_write_tokens
  );
}

function usd(value: number | null): string {
  return value === null ? "—" : `≈ $${value.toFixed(2)}`;
}

export default async function UsagePage() {
  const report = await load<UsageReport>("/usage", "/app/usage");

  if (report.error !== undefined) {
    return (
      <section className="tile">
        <h2>Расход</h2>
        <p className="tile__empty">{report.error}</p>
      </section>
    );
  }

  const data = report.data;
  const models = data.by_model.map((item) => item.model);

  if (data.documents === 0) {
    return (
      <>
        <Head />
        <section className="tile wk-empty">
          <span aria-hidden="true">💸</span>
          <h2>Тратить пока не на что</h2>
          <p>
            Расход появляется после первого перевода. Пока ни одна книга не
            переводилась моделью, считать нечего — и показывать нули вместо
            этого незачем.
          </p>
          <Link className="btn btn--primary" href="/app/documents">
            К документам
          </Link>
        </section>
      </>
    );
  }

  const share: Part[] = data.by_model.map((item) => ({
    key: item.model,
    value: all(item.money.tokens),
    color: colorFor(models, item.model),
    label: item.model,
  }));

  const months = data.by_month.map((month) => ({
    month: month.month,
    total: all(month.money.tokens),
    parts: month.by_model.map((item) => ({
      key: item.model,
      value: all(item.money.tokens),
      color: colorFor(models, item.model),
      label: item.model,
    })),
  }));

  return (
    <>
      <Head />

      <div className="wk-facts">
        <Fact
          value={usd(data.total.usd)}
          label="оценка стоимости"
          mark="💸"
          strong
        />
        <Fact
          value={thousands(data.total.tokens.input_tokens)}
          label="токенов на входе"
          mark="📥"
        />
        <Fact
          value={thousands(data.total.tokens.output_tokens)}
          label="токенов на выходе"
          mark="📤"
        />
        <Fact
          value={thousands(data.documents)}
          label={plural(data.documents, "книга", "книги", "книг")}
          mark="📚"
        />
      </div>

      <div className="cab__row cab__row--split">
        <section className="tile">
          <div className="tile__head">
            <h3>Когда тратили</h3>
            <span className="tile__note">по месяцу загрузки книги</span>
          </div>

          <Months months={months} />

          <p className="tile__note wk-seg__foot">
            Столбец разложен по моделям — по нему видно, от чего изменился
            счёт: перевели больше или сменили модель. Месяц — тот, когда
            книгу загрузили: отдельной записи «когда потратили» в базе нет,
            а дата загрузки не меняется никогда.
          </p>
        </section>

        <section className="tile">
          <div className="tile__head">
            <h3>Чем переводили</h3>
            <span className="tile__note">доли по токенам</span>
          </div>

          <Share parts={share} />
          <Legend parts={share} />

          <div className="us-models">
            {data.by_model.map((item) => (
              <div className="us-model" key={item.model}>
                <span>
                  <i style={{ background: colorFor(models, item.model) }} aria-hidden="true" />
                  {item.model}
                </span>
                <span className="tile__note">
                  {thousands(item.documents)}{" "}
                  {plural(item.documents, "книга", "книги", "книг")}
                </span>
                <b>{usd(item.money.usd)}</b>
              </div>
            ))}
          </div>
        </section>
      </div>

      <section className="tile">
        <div className="tile__head">
          <h3>На что ушло</h3>
          <span className="tile__note">самые дорогие книги</span>
        </div>

        <div className="us-table" role="table">
          <div className="us-row us-row--head" role="row">
            <span role="columnheader">Книга</span>
            <span role="columnheader">Модель</span>
            <span role="columnheader">Вход</span>
            <span role="columnheader">Выход</span>
            <span role="columnheader">Оценка</span>
          </div>

          {data.by_document.map((spend) => (
            <Link
              className="us-row"
              key={spend.document_id}
              href={`/app/documents/${spend.document_id}`}
              role="row"
            >
              <span className="us-row__name" role="cell">
                <b>{spend.title}</b>
                <span className="tile__note">{spend.project_name}</span>
              </span>
              <span className="us-row__model" role="cell">
                {spend.translated_by === null ? (
                  <span className="tile__note">без модели</span>
                ) : (
                  <>
                    <i
                      style={{ background: colorFor(models, spend.translated_by) }}
                      aria-hidden="true"
                    />
                    {spend.translated_by}
                  </>
                )}
              </span>
              <span role="cell">{thousands(spend.money.tokens.input_tokens)}</span>
              <span role="cell">{thousands(spend.money.tokens.output_tokens)}</span>
              <span className="us-row__usd" role="cell">
                {usd(spend.money.usd)}
              </span>
            </Link>
          ))}
        </div>

        <p className="tile__note wk-seg__foot">
          «Без модели» — книга, переведённая целиком памятью переводов и
          повторами: модель не вызывалась, и расхода нет. Это не то же самое,
          что прочерк в оценке, — тот означает модель вне прейскуранта, чья
          цена неизвестна.
        </p>
      </section>

      {data.total.tokens.cached_input_tokens > 0 && (
        <section className="tile us-cache">
          <div className="tile__head">
            <h3>Кэш</h3>
            <span className="tile__note">десятая часть цены обычного ввода</span>
          </div>

          <div className="wk-money">
            <div className="wk-money__row">
              <span>Прочитано из кэша</span>
              <b>{thousands(data.total.tokens.cached_input_tokens)}</b>
            </div>
            <div className="wk-money__row">
              <span>Записано в кэш</span>
              <b>{thousands(data.total.tokens.cache_write_tokens)}</b>
            </div>
          </div>

          <p className="tile__note wk-seg__foot">
            Системные правила перевода одинаковы на всю книгу, поэтому они
            записываются в кэш один раз и дальше читаются вдесятеро дешевле.
            Отдельной строкой — ровно затем, чтобы эта экономия была видна.
          </p>
        </section>
      )}

      <p className="tile__note wk-seg__foot us-foot">
        Суммы — оценка по прейскуранту модели в долларах, а не счёт. Хранятся
        токены: цены меняются, а потраченное на книгу — исторический факт, и
        пересчитывать его задним числом по новому прейскуранту значит
        подделывать отчёт. Настоящий счёт приходит от поставщика и бывает
        меньше — у него свои скидки за объём и пробные периоды.
      </p>
    </>
  );
}

function Head() {
  return (
    <header className="wk-head">
      <div>
        <h1>Расход</h1>
        <p className="tile__note">
          Во что обошёлся перевод: когда тратили, какой моделью и на какие
          книги.
        </p>
      </div>
    </header>
  );
}

function Fact({
  value,
  label,
  mark,
  strong,
}: {
  value: string;
  label: string;
  mark: string;
  strong?: boolean;
}) {
  return (
    <section className={strong ? "stat wk-fact us-fact--money" : "stat wk-fact"}>
      <span className="stat__mark" aria-hidden="true">
        {mark}
      </span>
      <div className="stat__value">{value}</div>
      <div className="stat__label">{label}</div>
    </section>
  );
}
