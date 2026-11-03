"use client";

/* Правило двух человек для критичных ошибок.

   Выключено по умолчанию: в команде из одного редактора оно остановило бы работу, а новых
   ролей в процессе нет. Включение и выключение остаётся в журнале решений. */

import { useActionState } from "react";

import { saveReview, type ModelResult, type WorkspaceSettings } from "./actions";
import { ReportError } from "../ui/toast";

const EMPTY: ModelResult = {};

export function Review({ settings }: { settings: WorkspaceSettings }) {
  const [state, action, busy] = useActionState(saveReview, EMPTY);
  const current = state.saved ?? settings;

  return (
    <section className="tile st-block">
      <div className="tile__head">
        <h3>Проверки и решения</h3>
        <span className="tile__note">кто решает и что сверяет модель</span>
      </div>

      {/* Форма пересобирается после записи, как остальные: иначе флажок покажется сброшенным. */}
      <form key={state.savedAt ?? 0} action={action} className="st-form">
        <label className="st-switch st-switch--block">
          <input
            type="checkbox"
            name="two_person_review"
            value="yes"
            defaultChecked={current.two_person_review}
          />
          <span>
            Критичную ошибку решает не тот, кто её нашёл или исправил
            <small className="st-switch__note">
              Нашедший не сможет подтвердить или отклонить своё замечание, а исправивший — проверить
              своё исправление. Если редактор в команде один, правило остановит работу.
            </small>
          </span>
        </label>

        <label className="st-switch">
          <input
            type="checkbox"
            name="minor_blocks_release"
            value="yes"
            defaultChecked={current.minor_blocks_release}
          />
          <span>
            Незначительные замечания тоже держат выпуск
            <small className="st-switch__note">
              Критичные и серьёзные держат его всегда. С этой настройкой выпуск не пройдёт контроль и
              при незакрытых незначительных.
            </small>
          </span>
        </label>

        <label className="field">
          <span>Что отдавать на смысловую сверку</span>
          <select name="semantic_scope" defaultValue={current.semantic_scope}>
            <option value="risky">Только рискованное</option>
            <option value="all">Все блоки, кроме листингов</option>
          </select>
          <small>
            Рискованное — числа, формулы и код внутри текста, таблицы, подписи, предупреждения,
            обязательные термины. Сверка всей книги примерно удваивает расход на модель.
          </small>
        </label>

        <label className="field">
          <span>Когда исправление попадает в память переводов</span>
          <select name="memory_publish_on" defaultValue={current.memory_publish_on}>
            <option value="verified">После проверки исправления</option>
            <option value="closed">Только после закрытия замечания</option>
          </select>
          <small>
            Память выдаёт текст без модели и без проверки, поэтому раньше проверки туда ничего не
            попадает. Если ждать закрытия, память наполняется медленнее.
          </small>
        </label>

        <div className="wk-actions">
          <button className="btn btn--primary" type="submit" disabled={busy}>
            {busy ? "Сохраняем…" : "Сохранить"}
          </button>
        </div>
      </form>

      <ReportError error={state.error} at={state} />

      {state.saved !== undefined && state.error === undefined && (
        <p className="wk-note" role="status">
          <span aria-hidden="true">✅</span> Записано: правило двух человек{" "}
          {current.two_person_review ? "включено" : "выключено"}, на сверку идёт{" "}
          {current.semantic_scope === "all" ? "всё" : "только рискованное"}.
        </p>
      )}
    </section>
  );
}
