"use client";

/* Заведение проекта.

   Проект — это языковая пара плюс словарь: книги внутри одного проекта
   переводятся согласованно между собой, а память переводов и термины
   накапливаются на пару языков. Поэтому языки спрашиваются при создании и
   потом не меняются: сменить их у проекта с переведёнными книгами значит
   объявить весь накопленный словарь негодным.

   Форма свёрнута, пока её не попросили: на экране со списком главное —
   список, а не пустые поля над ним. */

import { useActionState, useState, type ReactNode } from "react";

import { createProject, type Result } from "../actions";

const EMPTY: Result = {};

// Языки, с которых и на которые работают чаще всего. Список не полный и
// полным быть не может: код языка по BCP 47 — это тысячи значений, а
// выбрать из тысячи в раскрывающемся списке нельзя. Всё остальное
// вводится вручную соседним полем.
const LANGUAGES = [
  { code: "en", title: "Английский" },
  { code: "ru", title: "Русский" },
  { code: "de", title: "Немецкий" },
  { code: "fr", title: "Французский" },
  { code: "it", title: "Итальянский" },
  { code: "es", title: "Испанский" },
  { code: "zh", title: "Китайский" },
  { code: "tr", title: "Турецкий" },
];

/* Форма закрывается после удачного создания не сама, а вместе со всей
   страницей: серверное действие обновляет список, число проектов меняется,
   и страница пересобирает эту форму заново — по ключу (см. page.tsx).
   Закрывать её здесь, глядя на результат действия, значит писать состояние
   из эффекта и получать лишний круг отрисовки. */
export function NewProject({
  first,
  children,
}: {
  first: boolean;
  children: ReactNode;
}) {
  // Первый проект заводят сразу — без него в кабинете нечего делать, и
  // прятать форму за кнопкой значит прятать единственное доступное
  // действие.
  const [open, setOpen] = useState(first);
  const [state, action, busy] = useActionState(createProject, EMPTY);

  /* Заголовок раздела приходит сюда содержимым, а не живёт отдельно: кнопка
     стоит в его строке справа, а форма раскрывается под ним — значит обе
     части принадлежат одному узлу дерева. Текст заголовка при этом остаётся
     серверным, в браузер уезжает только кнопка. */
  return (
    <>
      <header className="wk-head">
        {children}

        <button
          className="btn btn--primary"
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((was) => !was)}
        >
          Новый проект <i aria-hidden="true">+</i>
        </button>
      </header>

      {open && <Form action={action} busy={busy} state={state} onClose={() => setOpen(false)} />}
    </>
  );
}

function Form({
  action,
  busy,
  state,
  onClose,
}: {
  action: (formData: FormData) => void;
  busy: boolean;
  state: Result;
  onClose: () => void;
}) {
  return (
    <section className="tile wk-form">
      <div className="tile__head">
        <h3>Новый проект</h3>
        <span className="tile__note">языковая пара задаётся один раз</span>
      </div>

      <form action={action} className="wk-grid">
        <label className="field wk-grid__wide">
          <span>Название</span>
          <input
            name="name"
            type="text"
            required
            minLength={2}
            maxLength={200}
            placeholder="Документация к API платформы"
            autoComplete="off"
          />
        </label>

        <label className="field">
          <span>Язык оригинала</span>
          <select name="source_language" defaultValue="en">
            {LANGUAGES.map((language) => (
              <option key={language.code} value={language.code}>
                {language.title}
              </option>
            ))}
          </select>
        </label>

        <label className="field">
          <span>Язык перевода</span>
          <select name="target_language" defaultValue="ru">
            {LANGUAGES.map((language) => (
              <option key={language.code} value={language.code}>
                {language.title}
              </option>
            ))}
          </select>
        </label>

        <label className="field wk-grid__wide">
          <span>Описание</span>
          <input
            name="description"
            type="text"
            maxLength={5000}
            placeholder="Чем этот проект отличается от соседнего"
            autoComplete="off"
          />
        </label>

        <div className="wk-grid__wide wk-actions">
          <button className="btn btn--primary" type="submit" disabled={busy}>
            {busy ? "Создаём…" : "Создать проект"}
          </button>
          <button className="btn btn--ghost" type="button" onClick={onClose}>
            Отмена
          </button>
        </div>
      </form>

      {state.error !== undefined && (
        <p className="form__error" role="alert">
          {state.error}
        </p>
      )}
    </section>
  );
}
