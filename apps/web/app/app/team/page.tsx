import type { Metadata } from "next";

import { currentUser } from "../../lib/current-user";
import { load, type Team } from "../../lib/work";
import { ROLE_LABEL } from "../labels";
import "../work.css";
import "../settings/settings.css";
import "./team.css";
import { TeamBoard } from "./board";

export const metadata: Metadata = {
  title: "Команда — BookTranslate",
  description: "Кто работает в рабочем пространстве и с какими правами.",
};

/* Команда рабочего пространства.

   Доступ сюда открывает владелец, а не администратор площадки: площадка
   одобрила заказчика, а кого он пускает к своим книгам — его дело. */

export default async function TeamPage() {
  const team = await load<Team>("/team", "/app/team");
  const me = await currentUser("/app/team");

  return (
    <>
      <header className="wk-head tm-head">
        <div>
          <h1>Команда</h1>
          <p className="tile__note">
            Кто работает в этом пространстве и что кому разрешено.
            {team.data !== undefined &&
              ` Ваша роль — ${(ROLE_LABEL[team.data.my_role] ?? team.data.my_role).toLowerCase()}.`}
          </p>
        </div>
      </header>

      {team.error !== undefined ? (
        <section className="tile">
          <p className="tile__empty">{team.error}</p>
        </section>
      ) : (
        <TeamBoard team={team.data} me={me?.user.email ?? null} />
      )}
    </>
  );
}
