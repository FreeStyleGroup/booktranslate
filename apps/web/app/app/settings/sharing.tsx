"use client";

/* Тематика и общий словарь площадки.

   Тематика открывает подсказки: термины, которыми поделились другие
   пространства той же области. Без неё подсказок нет — «bank» из
   банковского словаря не должен лезть в книгу про реки.

   Разрешение отдаёт площадке термины загруженных словарей — только
   термины, не текст книг: память переводов не делится никогда. По
   умолчанию выключено: чужой словарь по умолчанию чужой. Действует на
   следующие загрузки; отданное раньше остаётся отданным. */

import { useActionState } from "react";

import { saveSharing, type ModelResult, type WorkspaceSettings } from "./actions";

const EMPTY: ModelResult = {};

export function Sharing({ settings }: { settings: WorkspaceSettings }) {
  const [state, action, busy] = useActionState(saveSharing, EMPTY);
  const current = state.saved ?? settings;
  const subject = current.subjects.find((item) => item.id === current.subject);

  return (
    <section className="tile st-block">
      <div className="tile__head">
        <h3>Тематика и общий словарь</h3>
        <span className="tile__note">обмен терминами между пространствами</span>
      </div>

      <p className="tile__note st-lead">
        На площадке есть общий словарь: термины, которыми пространства
        поделились и которые одобрил администратор. Он подсказывает — по
        тематике, и никогда не спорит с вашим словарём.
      </p>

      {/* 🔥 Форма пересобирается после каждой записи — по ключу, как и
          остальные формы настроек: иначе флажок после записи остаётся
          сброшенным. */}
      <form key={state.savedAt ?? 0} action={action} className="st-form">
        <label className="field">
          <span>Тематика пространства</span>
          <select name="subject" defaultValue={current.subject ?? ""}>
            <option value="">Не указана — подсказок нет</option>
            {current.subjects.map((item) => (
              <option key={item.id} value={item.id}>
                {item.title}
              </option>
            ))}
          </select>
          <small>
            По ней вы получаете подсказки из общего словаря, и по ней же
            ваши термины попадут к другим — если разрешите ниже.
          </small>
        </label>

        <label className="st-switch st-switch--block">
          <input
            type="checkbox"
            name="share_glossary"
            value="yes"
            defaultChecked={current.share_glossary}
          />
          <span>
            Разрешить площадке брать термины загружаемых словарей в общий
            <small className="st-switch__note">
              Только термины — слово и перевод. Текст книг и память переводов
              не отдаются никогда. Действует на следующие загрузки; у каждой
              загрузки разрешение можно поменять на месте.
            </small>
          </span>
        </label>

        <div className="wk-actions">
          <button className="btn btn--primary" type="submit" disabled={busy}>
            {busy ? "Сохраняем…" : "Сохранить"}
          </button>
        </div>
      </form>

      {state.error !== undefined && (
        <p className="form__error" role="alert">
          {state.error}
        </p>
      )}

      {state.saved !== undefined && state.error === undefined && (
        <p className="wk-note" role="status">
          <span aria-hidden="true">✅</span> Записано: тематика{" "}
          {subject === undefined ? "не указана" : `«${subject.title}»`}, общий словарь{" "}
          {current.share_glossary ? "разрешён" : "не разрешён"}.
        </p>
      )}
    </section>
  );
}
