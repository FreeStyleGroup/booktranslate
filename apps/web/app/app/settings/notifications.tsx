"use client";

/* Куда сообщать о готовности книги.

   Смысл блока: книга переводится часами и без человека, а значит работа
   кончается не переводом, а сообщением о том, что перевод кончился.

   Экран обязан говорить правду о том, чего пока нет. Отправка не
   подключена ни в одном канале, и настройки можно заполнить, но письмо не
   уйдёт. Сказать это надо прямо и наверху, а не мелким шрифтом внизу:
   включённый канал, который молчит, читается как поломка.

   Про Телеграм то же самое, но с добавкой: **бот не может написать
   человеку по нику**. Телеграму нужен номер разговора, а тот появляется
   только после того, как человек сам напишет боту. Ник — необходимое
   условие, но не достаточное, и написано это там же, где вводят ник. */

import { useActionState, useState } from "react";

import { saveNotifications, type NotificationSettings, type Result } from "./actions";

const EMPTY: Result = {};

export function Notifications({
  settings,
  mine,
}: {
  settings: NotificationSettings;
  // Почта того, кто смотрит. Показывается, а не спрашивается: письмо уходит
  // заказчику перевода на почту его учётной записи, и она уже проверена при
  // входе.
  mine: string | null;
}) {
  const [state, action, busy] = useActionState(saveNotifications, EMPTY);
  const current = state.saved ?? settings;

  return (
    <section className="tile st-block">
      <div className="tile__head">
        <h3>Уведомления о готовности</h3>
        <span className="tile__note">на всё рабочее пространство</span>
      </div>

      <p className="tile__note st-lead">
        Книгу переводит сервер, и человек в это время может заниматься чем
        угодно. Чтобы не заглядывать в кабинет, укажите, куда сообщить, когда
        перевод закончится.
      </p>

      {/* 🔥 Форма пересобирается после каждой записи — по ключу.

          Иначе так: React после серверного действия сбрасывает форму, и
          флажок, у которого в разметке ничего не изменилось, React не
          трогает — сброшенное значение остаётся. Флажок гаснет, хотя канал
          включён, и рядом об этом же написано «Записано, канал включён».
          Интерфейс, противоречащий сам себе в двух сантиметрах, хуже
          отсутствующего. */}
      <Form
        key={state.savedAt ?? 0}
        current={current}
        mine={mine}
        action={action}
        busy={busy}
      />

      {state.error !== undefined && (
        <p className="form__error" role="alert">
          {state.error}
        </p>
      )}

      {state.saved !== undefined && state.error === undefined && (
        <p className="wk-note" role="status">
          <span aria-hidden="true">✅</span> Записано.{" "}
          {state.saved.email_enabled || state.saved.telegram_enabled
            ? "Канал включён — сообщения пойдут по нему, как только отправку подключат."
            : "Все каналы выключены: о готовности книги сообщать некуда."}
        </p>
      )}
    </section>
  );
}

function Form({
  current,
  mine,
  action,
  busy,
}: {
  current: NotificationSettings;
  mine: string | null;
  action: (formData: FormData) => void;
  busy: boolean;
}) {
  const [email, setEmail] = useState(current.email_enabled);
  const [telegram, setTelegram] = useState(current.telegram_enabled);

  return (
    <form action={action} className="st-form">
      <div className={email ? "st-channel is-on" : "st-channel"}>
        <label className="st-switch">
          <input
            name="email_enabled"
            type="checkbox"
            value="yes"
            checked={email}
            onChange={(event) => setEmail(event.target.checked)}
          />
          <span>Почта</span>
        </label>

        {/* Почта учётной записи показана, а не спрошена: она известна и
            проверена при входе, а второе поле для того же адреса — это
            второе место, где его можно опечатать. */}
        {/* Без значка. Значок в 13 точек на этой полосе превращается в
            неразборчивое пятно и читается как несработавшая картинка, а
            различать состояния он не помогает: их различает подложка. */}
        <p className="st-state">
          Письмо-уведомление уйдёт на вашу основную почту, указанную при
          регистрации аккаунта{mine === null ? "." : ": "}
          {mine !== null && <b>{mine}</b>}
        </p>

        <label className="field">
          <span>Ещё один адрес</span>
          <input
            name="email_extra"
            type="email"
            maxLength={320}
            defaultValue={current.email_extra ?? ""}
            placeholder="Например, общий ящик бюро"
            autoComplete="off"
          />
        </label>

        <p className="tile__note">
          Необязательно. Сюда придёт та же копия — общему ящику, менеджеру
          проекта или почтовому списку. Совпадающие адреса не задваиваются.
        </p>

        {!current.email_ready && (
          <p className="st-state">
            Почтовый ящик площадки ещё не настроен на сервере: настройки
            сохранятся и заработают сами, как только его пропишут.
          </p>
        )}
      </div>

      <div className={telegram ? "st-channel is-on" : "st-channel"}>
        <label className="st-switch">
          <input
            name="telegram_enabled"
            type="checkbox"
            value="yes"
            checked={telegram}
            onChange={(event) => setTelegram(event.target.checked)}
          />
          <span>Телеграм</span>
        </label>

        <label className="field">
          <span>Ник в Телеграме</span>
          <input
            name="telegram_username"
            type="text"
            maxLength={33}
            defaultValue={current.telegram_username === null ? "" : `@${current.telegram_username}`}
            placeholder="@ivanov"
            autoComplete="off"
          />
        </label>

        {current.telegram_username !== null && (
          <p className={current.telegram_linked ? "st-state is-ok" : "st-state"}>
            {current.telegram_linked
              ? "Бот вас узнал — сообщения придут сюда."
              : "Бот вас пока не знает: Телеграм не даёт писать по нику. Напишите боту, и адрес определится сам."}
          </p>
        )}

        <p className="tile__note">
          Бот у площадки один — заводить своего не нужно. Указывайте ник того,
          кому идти за книгой; сменить его можно в любой момент.
        </p>

        {!current.telegram_ready && (
          <p className="st-state">
            Бот площадки ещё делается: ник сохранится и заработает сам, как
            только бот появится.
          </p>
        )}
      </div>

      <div className="wk-actions">
        <button className="btn btn--primary" type="submit" disabled={busy}>
          {busy ? "Сохраняем…" : "Сохранить"}
        </button>
      </div>
    </form>
  );
}
