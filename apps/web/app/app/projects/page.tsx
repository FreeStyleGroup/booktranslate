import type { Metadata } from "next";
import Link from "next/link";

import { load, type Document, type Project } from "../../lib/work";
import { plural, thousands, when } from "../labels";
import "../work.css";
import { NewProject } from "./new-project";

export const metadata: Metadata = {
  title: "Проекты — BookTranslate",
  description: "Языковые пары, словари и книги заказчиков.",
};

/* Проекты.

   Проект — это языковая пара, словарь и книги одного заказчика. Всё, что
   накапливается по ходу работы — термины, память переводов, решения по
   спорным местам, — держится за пару языков, поэтому и книги делятся по
   проектам, а не лежат общей кучей.

   Рядом с каждым проектом показано число книг: без него список проектов —
   это список названий, по которому не видно, где идёт работа. */

export default async function ProjectsPage() {
  const projects = await load<Project[]>("/projects?limit=200", "/app/projects");
  const documents = await load<Document[]>("/documents?limit=200", "/app/projects");

  if (projects.error !== undefined) {
    return (
      <section className="tile">
        <h2>Проекты</h2>
        <p className="tile__empty">{projects.error}</p>
      </section>
    );
  }

  const counts = new Map<string, number>();

  for (const document of documents.data ?? []) {
    counts.set(document.project_id, (counts.get(document.project_id) ?? 0) + 1);
  }

  return (
    <>
      {/* Ключ по числу проектов: после удачного создания список
          обновляется, ключ меняется — и форма собирается заново уже
          закрытой и пустой, без возни с её состоянием изнутри. */}
      <NewProject key={projects.data.length} first={projects.data.length === 0}>
        <div>
          <h1>Проекты</h1>
          <p className="tile__note">
            Языковая пара, словарь и книги одного заказчика. Термины и память
            переводов копятся внутри проекта.
          </p>
        </div>
      </NewProject>

      {projects.data.length === 0 && (
        <section className="tile wk-empty">
          <span aria-hidden="true">🗃</span>
          <h2>Здесь пока пусто</h2>
          <p>
            Заведите первый проект — он задаёт языковую пару. Дальше в него
            загружаются книги: разбор, терминология и перевод идут уже внутри.
          </p>
        </section>
      )}

      {projects.data.length > 0 && (
        <div className="wk-cards">
          {projects.data.map((project) => (
            <article className="tile wk-card" key={project.id}>
              <div className="wk-card__top">
                <h3>{project.name}</h3>
                <span className="chip chip--info">
                  {project.source_language} → {project.target_language}
                </span>
              </div>

              {project.description !== null && project.description !== "" && (
                <p className="wk-card__lead">{project.description}</p>
              )}

              <div className="wk-card__foot">
                <span className="tile__note">
                  {books(counts.get(project.id) ?? 0)} · заведён {when(project.created_at)}
                </span>

                <Link
                  className="btn btn--ghost btn--small"
                  href={`/app/documents?project=${project.id}`}
                >
                  Книги проекта
                </Link>
              </div>
            </article>
          ))}
        </div>
      )}
    </>
  );
}

/** «3 книги» или «книг пока нет» — число без слова читается хуже. */
function books(amount: number): string {
  if (amount === 0) {
    return "книг пока нет";
  }

  return `${thousands(amount)} ${plural(amount, "книга", "книги", "книг")}`;
}
