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
        <h3>Проверка критичных ошибок</h3>
        <span className="tile__note">кто вправе решать</span>
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

        <div className="wk-actions">
          <button className="btn btn--primary" type="submit" disabled={busy}>
            {busy ? "Сохраняем…" : "Сохранить"}
          </button>
        </div>
      </form>

      <ReportError error={state.error} at={state} />

      {state.saved !== undefined && state.error === undefined && (
        <p className="wk-note" role="status">
          <span aria-hidden="true">✅</span> Записано: правило{" "}
          {current.two_person_review ? "включено" : "выключено"}.
        </p>
      )}
    </section>
  );
}
