import type { Metadata } from "next";
import Link from "next/link";

import { currentUser } from "../../lib/current-user";
import { organizationId } from "../../lib/session";
import { load, type Document, type Project } from "../../lib/work";
import { plural, thousands, when } from "../labels";
import "../work.css";
import { DeleteProject } from "./delete-project";
import { NewProject } from "./new-project";

// Кто удаляет проекты — те же, кто их заводит: это решение о деньгах и
// сроках, а не работа с текстом. Списано с проверки прав в API.
const MANAGING = new Set(["owner", "admin", "manager"]);

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
  const [projects, documents, me, organization] = await Promise.all([
    load<Project[]>("/projects?limit=200", "/app/projects"),
    load<Document[]>("/documents?limit=200", "/app/projects"),
    currentUser("/app/projects"),
    organizationId(),
  ]);

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

  const membership =
    me?.memberships.find((item) => item.organization_id === organization) ?? me?.memberships[0];
  const manages = membership !== undefined && MANAGING.has(membership.role);

  return (
    <>
      {/* Ключ по числу проектов: после удачного создания список
          обновляется, ключ меняется — и форма собирается заново уже
          закрытой и пустой, без возни с её состоянием изнутри. */}
      <NewProject key={projects.data.length} first={projects.data.length === 0}>
        <div>
          <h1>Проекты</h1>
          <p className="tile__note">
            Языковая пара, словарь и книги одного заказчика. Термины и память переводов копятся
            внутри проекта.
          </p>
        </div>
      </NewProject>

      {projects.data.length === 0 && (
        <section className="tile wk-empty">
          <span aria-hidden="true">🗃</span>
          <h2>Здесь пока пусто</h2>
          <p>
            Заведите первый проект — он задаёт языковую пару. Дальше в него загружаются книги:
            разбор, терминология и перевод идут уже внутри.
          </p>
        </section>
      )}

      {projects.data.length > 0 && (
        <div className="wk-cards">
          {projects.data.map((project) => (
            <article className="tile wk-card" key={project.id}>
              <div className="wk-card__top">
                <h3>{project.name}</h3>
                {/* Языковая пара и крестик — в углу, подальше от рабочей
                    кнопки внизу: удаление не должно стоять рядом с тем,
                    на что нажимают каждый день. */}
                <span className="wk-card__side">
                  <span className="chip chip--info">
                    {project.source_language} → {project.target_language}
                  </span>
                  {manages && (
                    <DeleteProject
                      id={project.id}
                      name={project.name}
                      books={counts.get(project.id) ?? 0}
                    />
                  )}
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
