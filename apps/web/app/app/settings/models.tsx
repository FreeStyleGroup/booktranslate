"use client";

/* Чем переводить.

   Выбор принадлежит пространству, а не площадке: цену решения платит
   заказчик. Плитки — из каталога API, с ценой из его же прейскуранта:
   свой список моделей в витрине разошёлся бы с ценами при первой их смене.

   «По умолчанию площадки» — отдельное состояние, а не одна из плиток: оно
   отличается от «выбрали то же, что и умолчание» тем, что смена умолчания
   площадки первое затронет, а второе — нет. */

import { useActionState } from "react";

import { saveModel, type ModelResult, type WorkspaceSettings } from "./actions";

const EMPTY: ModelResult = {};

export function Models({ settings }: { settings: WorkspaceSettings }) {
  const [state, action, busy] = useActionState(saveModel, EMPTY);
  const current = state.saved ?? settings;
  const chosen = current.models.find((model) => model.id === current.translation_model);

  return (
    <section className="tile st-block">
      <div className="tile__head">
        <h3>Модель перевода</h3>
        <span className="tile__note">на все следующие запуски</span>
      </div>

      <p className="tile__note st-lead">
        Смена модели меняет и счёт, и качество. Уже переведённое не
        пересчитывается — у каждого сегмента записано, чем его переводили.
      </p>

      {!current.provider_ready && (
        <p className="st-state">
          Сейчас на сервере включена заглушка перевода. Выбор сохранится и
          заработает, как только включат настоящую модель.
        </p>
      )}

      {/* 🔥 Форма пересобирается после каждой записи — по ключу: React
          после серверного действия сбрасывает форму, и переключатель, у
          которого в разметке ничего не изменилось, остался бы сброшенным. */}
      <form key={state.savedAt ?? 0} action={action} className="st-form">
        <div className="st-models" role="radiogroup" aria-label="Модель перевода">
          {current.models.map((model) => (
            <label
              className={
                "st-model" + (model.id === current.translation_model ? " is-active" : "")
              }
              key={model.id}
            >
              <input
                type="radio"
                name="translation_model"
                value={model.id}
                defaultChecked={model.id === current.translation_model}
              />
              <span className="st-model__top">
                <b>{model.title}</b>
                {model.id === current.default_model && (
                  <span className="chip chip--info">по умолчанию площадки</span>
                )}
              </span>
              <span className="st-model__note">{model.note}</span>
              <span className="st-model__price">
                {model.input_usd === null || model.output_usd === null
                  ? "цена не в прейскуранте"
                  : `$${model.input_usd} вход · $${model.output_usd} выход — за миллион токенов`}
              </span>
            </label>
          ))}
        </div>

        <div className="wk-actions">
          <button className="btn btn--primary" type="submit" disabled={busy}>
            {busy ? "Сохраняем…" : "Сохранить"}
          </button>

          {current.chosen_model !== null && (
            <button
              className="btn btn--ghost"
              type="submit"
              name="reset"
              value="yes"
              disabled={busy}
            >
              Вернуться к умолчанию площадки
            </button>
          )}
        </div>
      </form>

      {state.error !== undefined && (
        <p className="form__error" role="alert">
          {state.error}
        </p>
      )}

      {state.saved !== undefined && state.error === undefined && (
        <p className="wk-note" role="status">
          <span aria-hidden="true">✅</span> Записано: переводить будет{" "}
          {chosen?.title ?? current.translation_model}
          {current.chosen_model === null && " — умолчание площадки"}.
        </p>
      )}
    </section>
  );
}
