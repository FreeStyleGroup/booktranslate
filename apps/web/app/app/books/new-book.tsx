"use client";

/* Заведение книги.

   Спрашиваются только те сведения, которых сервис не знает: проект,
   название, автор и пометка издания. Код выдаёт сервер — он входит в
   номера замечаний, и давать его вводить значит разрешить два издания с
   одним номером. Языковую пару книга берёт у проекта: спросить её второй
   раз — дать ей разойтись с глоссарием и памятью проекта.

   Форма свёрнута, пока её не попросили: на экране со списком главное —
   список, а не пустые поля над ним. */

import { useActionState, useState, type ReactNode } from "react";

import type { Project } from "../../lib/work";
import { createBook, type Result } from "./actions";

const EMPTY: Result = {};

export function NewBook({
  projects,
  current,
  children,
}: {
  projects: Project[];
  /** Проект из отбора: заводят книгу обычно в том, который сейчас
   *  смотрят, и подставить его точнее, чем первый по списку. */
  current: string | undefined;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  // Удачное заведение уводит на карточку книги прямо из действия, поэтому
  // здесь нужен только отказ: успеха эта форма не дожидается.
  const [state, action, busy] = useActionState(createBook, EMPTY);

  return (
    <>
      <header className="wk-head">
        {children}

        {projects.length > 0 && (
          <button
            className="btn btn--primary"
            type="button"
            aria-expanded={open}
            onClick={() => setOpen((was) => !was)}
          >
            Новая книга <i aria-hidden="true">+</i>
          </button>
        )}
      </header>

      {open && (
        <section className="tile wk-form">
          <div className="tile__head">
            <h3>Новая книга</h3>
            <span className="tile__note">код выдаст сервер</span>
          </div>

          <form action={action} className="wk-grid">
            <label className="field wk-grid__wide">
              <span>Название</span>
              <input
                name="title"
                type="text"
                required
                minLength={2}
                maxLength={500}
                placeholder="Advances in Financial Machine Learning"
                autoComplete="off"
              />
              <small>Так, как книга названа на титульном листе оригинала.</small>
            </label>

            <label className="field">
              <span>Проект</span>
              <select name="project_id" defaultValue={current ?? projects[0]?.id}>
                {projects.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.name} ({project.source_language} → {project.target_language})
                  </option>
                ))}
              </select>
            </label>

            <label className="field">
              <span>Автор</span>
              <input
                name="author"
                type="text"
                maxLength={300}
                placeholder="Marcos López de Prado"
                autoComplete="off"
              />
            </label>

            <label className="field wk-grid__wide">
              <span>Издание</span>
              <input
                name="edition_label"
                type="text"
                maxLength={200}
                placeholder="2-е издание, 2021"
                autoComplete="off"
              />
              <small>
                Пометка, по которой издания отличают друг от друга. У книги, выходившей один раз,
                её нет.
              </small>
            </label>

            <div className="wk-grid__wide wk-actions">
              <button className="btn btn--primary" type="submit" disabled={busy}>
                {busy ? "Заводим…" : "Завести книгу"}
              </button>
              <button className="btn btn--ghost" type="button" onClick={() => setOpen(false)}>
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
      )}
    </>
  );
}
