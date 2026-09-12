import type { Metadata } from "next";
import Link from "next/link";

import { currentUser } from "../../lib/current-user";
import { organizationId } from "../../lib/session";
import { load, type MemoryPage as Page } from "../../lib/work";
import { pages, plural, thousands } from "../labels";
import "../work.css";
import "./memory.css";
import { UnitList } from "./unit-list";

export const metadata: Metadata = {
  title: "Память переводов — BookTranslate",
  description: "Пары «исходник — перевод» по всем книгам и что они сберегли.",
};

/* Память переводов рабочего пространства.

   Отвечает на вопрос «мы это уже переводили?» — и на второй, который
   задаёт заказчик: «сколько я на этом сэкономил». Поэтому наверху не
   список, а числа: сколько пар, сколько раз они пригодились и во что это
   обошлось бы заново по текущей модели. Оценка сверху, как и смета, и
   помечена как оценка.

   Список — чаще пригодившиеся первыми: по ним видно, что именно окупает
   память. Правка на месте: поправленная пара становится человеческой и
   вытесняет машинный вариант в следующей книге. */

const PAGE = 50;
const ORIGINS = ["human", "machine"];
const EDITING = new Set(["owner", "admin", "manager", "translator", "reviewer"]);

function parseOffset(value: string | undefined): number {
  const parsed = Number.parseInt(value ?? "", 10);

  return Number.isInteger(parsed) && parsed > 0 ? parsed : 0;
}

function pageHref(query: string, origin: string, offset: number): string {
  const parameters = new URLSearchParams();

  if (query !== "") {
    parameters.set("query", query);
  }

  if (origin !== "") {
    parameters.set("origin", origin);
  }

  if (offset > 0) {
    parameters.set("offset", String(offset));
  }

  const suffix = parameters.toString();

  return suffix === "" ? "/app/memory" : `/app/memory?${suffix}`;
}

function usd(value: number | null): string {
  return value === null ? "—" : `≈ $${value.toFixed(2)}`;
}

export default async function MemoryPage({
  searchParams,
}: {
  searchParams: Promise<{ query?: string; origin?: string; offset?: string }>;
}) {
  const { query = "", origin = "", offset: offsetParam } = await searchParams;
  const offset = parseOffset(offsetParam);
  const chosenOrigin = ORIGINS.includes(origin) ? origin : "";
  const here = pageHref(query, chosenOrigin, offset);

  const parameters = new URLSearchParams();
  parameters.set("limit", String(PAGE));
  parameters.set("offset", String(offset));

  if (query !== "") {
    parameters.set("query", query);
  }

  if (chosenOrigin !== "") {
    parameters.set("origin", chosenOrigin);
  }

  const [page, me, organization] = await Promise.all([
    load<Page>(`/memory?${parameters.toString()}`, here),
    currentUser(here),
    organizationId(),
  ]);

  if (page.error !== undefined) {
    return (
      <section className="tile">
        <h2>Память переводов</h2>
        <p className="tile__empty">{page.error}</p>
      </section>
    );
  }

  const membership =
    me?.memberships.find((item) => item.organization_id === organization) ?? me?.memberships[0];
  const edits = membership !== undefined && EDITING.has(membership.role);

  const { summary } = page.data;
  // Учётные страницы округляются вверх до одной, а ноль знаков — это ноль
  // страниц, а не одна: память, которая ещё ничего не сберегла, не должна
  // показывать сбережённую страницу.
  const savedPages = summary.saved_characters === 0 ? 0 : pages(summary.saved_characters);
  const filtered = query !== "" || chosenOrigin !== "";
  const more = offset + page.data.items.length < page.data.total;

  return (
    <>
      <header className="wk-head mm-head">
        <div>
          <h1>Память переводов</h1>
          <p className="tile__note">
            Всё, что уже переводилось в пространстве. Совпавший сегмент берётся отсюда и в модель не
            уходит — за него не платят.
          </p>
        </div>
      </header>

      <div className="wk-facts">
        <Fact
          value={thousands(summary.units)}
          label={plural(summary.units, "пара", "пары", "пар")}
          mark="🧠"
        />
        <Fact
          value={thousands(summary.hits)}
          label={`${plural(summary.hits, "раз", "раза", "раз")} пригодились`}
          mark="🔁"
        />
        <Fact
          value={thousands(savedPages)}
          label={plural(
            savedPages,
            "страница не ушла в модель",
            "страницы не ушли в модель",
            "страниц не ушло в модель",
          )}
          mark="📄"
        />
        <Fact value={usd(summary.saved_usd)} label="сбережено, оценка" mark="💸" />
      </div>

      <p className="tile__note mm-note">
        Деньги — оценка сверху по текущей модели пространства: столько стоил бы перевод этих страниц
        заново. Прочерк — модель не в прейскуранте.
        {summary.human_units > 0 &&
          ` Пар, правленных человеком: ${thousands(summary.human_units)} — они надёжнее машинных и вытесняют их.`}
      </p>

      <section className="tile mm-block">
        <div className="tile__head">
          <h3>Пары</h3>
          <span className="tile__note">
            {filtered ? "по отбору " : "всего "}
            {thousands(page.data.total)}
          </span>
        </div>

        <form className="mm-filters" method="get">
          <input
            type="search"
            name="query"
            defaultValue={query}
            placeholder="Слово из исходника или перевода"
            aria-label="Поиск по памяти"
          />
          <select name="origin" defaultValue={chosenOrigin} aria-label="Происхождение">
            <option value="">Любое происхождение</option>
            <option value="human">Правка человека</option>
            <option value="machine">Перевод модели</option>
          </select>
          <button className="btn btn--ghost btn--small" type="submit">
            Показать
          </button>
          {filtered && (
            <Link className="btn btn--ghost btn--small" href="/app/memory">
              Сбросить
            </Link>
          )}
        </form>

        {page.data.items.length === 0 ? (
          <p className="tile__empty">
            {filtered
              ? "По этому отбору ничего нет."
              : "Память пуста: она наполняется сама по мере перевода книг. Переведите первую — и здесь появятся пары."}
          </p>
        ) : (
          <UnitList units={page.data.items} edits={edits} />
        )}

        {(offset > 0 || more) && (
          <nav className="mm-pager" aria-label="Страницы памяти">
            <span className="tile__note">
              Показаны {offset + 1}–{offset + page.data.items.length} из{" "}
              {thousands(page.data.total)}
            </span>
            <div className="wk-actions">
              {offset > 0 && (
                <Link
                  className="btn btn--ghost btn--small"
                  href={pageHref(query, chosenOrigin, Math.max(0, offset - PAGE))}
                >
                  ← Назад
                </Link>
              )}
              {more && (
                <Link
                  className="btn btn--ghost btn--small"
                  href={pageHref(query, chosenOrigin, offset + PAGE)}
                >
                  Дальше →
                </Link>
              )}
            </div>
          </nav>
        )}
      </section>
    </>
  );
}

function Fact({ value, label, mark }: { value: string; label: string; mark: string }) {
  return (
    <section className="stat wk-fact">
      <span className="stat__mark" aria-hidden="true">
        {mark}
      </span>
      <div className="stat__value">{value}</div>
      <div className="stat__label">{label}</div>
    </section>
  );
}
