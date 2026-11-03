"use client";

/* Выбор версий глав и сборка.

   Смена версии меняет адрес, а расхождения считает сервер под этот состав: здесь своего мнения о них
   нет. Блокирующие расхождения показываются до кнопки, а не отказом после нажатия. */

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import type { Assembly } from "../../../../lib/work";
import { ReportError, useToast } from "../../../ui/toast";
import { buildBookRelease } from "../../release-actions";

export function AssemblyForm({
  bookId,
  plan,
  canBuild,
  here,
}: {
  bookId: string;
  plan: Assembly;
  canBuild: boolean;
  here: string;
}) {
  const [major, setMajor] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const router = useRouter();
  const toast = useToast();

  const chosen = plan.items.map((item) => item.chosen_id);
  const ids = chosen.filter((item) => item !== null);
  const blockers = plan.problems.filter((item) => item.severity === "blocker");
  const warnings = plan.problems.filter((item) => item.severity === "warning");

  function choose(chapterId: string, releaseId: string): void {
    const next = plan.items
      .map((item) => (item.chapter_id === chapterId ? releaseId : item.chosen_id))
      .filter((item) => item !== null && item !== "");
    const query = new URLSearchParams(next.map((item) => ["chosen", item as string]));

    router.push(`${here}?${query}`);
  }

  function build(): void {
    setError(null);

    start(async () => {
      const result = await buildBookRelease(bookId, ids, major);

      if (result.error !== undefined) {
        setError(result.error);
        router.refresh();
        return;
      }

      toast.ok(
        result.created === false
          ? `Такой состав уже собран: ${result.code}`
          : `Собран выпуск ${result.code}`,
      );
      router.refresh();
    });
  }

  return (
    <section className={plan.ready ? "tile bk-gate is-open" : "tile bk-gate"}>
      <div className="tile__head">
        <h3>Состав выпуска</h3>
        <span className={plan.ready ? "chip chip--ok" : "chip chip--danger"}>
          {plan.ready ? "можно собирать" : `мешает: ${blockers.length}`}
        </span>
      </div>

      <ul className="bk-releases">
        {plan.items.map((item) => (
          <li key={item.chapter_id}>
            <label className="field">
              <span>
                {item.chapter_code ?? `Глава ${item.ordinal}`}
                {item.title !== null && ` · ${item.title}`}
              </span>
              {item.available.length === 0 ? (
                <small>Нет утверждённой финальной версии.</small>
              ) : (
                <select
                  value={item.chosen_id ?? ""}
                  disabled={pending}
                  onChange={(event) => choose(item.chapter_id, event.target.value)}
                >
                  <option value="">Не включать</option>
                  {item.available.map((version) => (
                    <option key={version.id} value={version.id}>
                      {version.code}
                    </option>
                  ))}
                </select>
              )}
            </label>
            {item.working_differs && (
              <p className="tile__note">Рабочий текст главы новее выбранной версии.</p>
            )}
          </li>
        ))}
      </ul>

      {blockers.length > 0 && (
        <ul className="bk-gate__list">
          {blockers.map((item, index) => (
            <li key={`${item.code}-${index}`}>{item.message}</li>
          ))}
        </ul>
      )}

      {warnings.length > 0 && (
        <ul className="bk-gate__list bk-gate__list--warn">
          {warnings.map((item, index) => (
            <li key={`${item.code}-${index}`}>{item.message}</li>
          ))}
        </ul>
      )}

      {canBuild && (
        <div className="wk-actions">
          <button
            className="btn btn--primary"
            type="button"
            disabled={pending || !plan.ready || ids.length === 0}
            onClick={build}
          >
            {pending ? "Собираем…" : "Собрать выпуск"}
          </button>
          <label className="bk-check-inline">
            <input
              type="checkbox"
              checked={major}
              onChange={(event) => setMajor(event.target.checked)}
            />
            <span>Новая старшая версия</span>
          </label>
        </div>
      )}

      <ReportError error={error} />
    </section>
  );
}
