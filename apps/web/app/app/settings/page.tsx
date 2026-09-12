import type { Metadata } from "next";

import { currentUser } from "../../lib/current-user";
import { load } from "../../lib/work";
import "../work.css";
import "./settings.css";
import { Models } from "./models";
import { Notifications } from "./notifications";
import { Sharing } from "./sharing";
import type { NotificationSettings, WorkspaceSettings } from "./actions";

export const metadata: Metadata = {
  title: "Настройки — BookTranslate",
  description: "Модель перевода, уведомления о готовности книги и настройки рабочего пространства.",
};

/* Настройки рабочего пространства.

   Три блока, и все — про пространство целиком: чем переводить, чем
   делиться и кому сообщать о готовности. Модель первой: она решает,
   сколько это будет стоить, а уведомление — лишь когда об этом узнают.

   Списка «что появится потом» на странице нет намеренно: обещания в
   интерфейсе стареют раньше, чем сбываются, и место им в журнале работ, а
   не перед глазами у того, кто пришёл настроить почту. */

export default async function SettingsPage() {
  const workspace = await load<WorkspaceSettings>("/settings/workspace", "/app/settings");
  const settings = await load<NotificationSettings>(
    "/settings/notifications",
    "/app/settings",
  );
  // Почта учётной записи — не поле формы, а то, что уже известно: письмо
  // уходит тому, кто поставил книгу в очередь, и вписывать свой же адрес
  // второй раз значит завести второе место, где его можно опечатать.
  const me = await currentUser("/app/settings");

  return (
    <>
      <header className="wk-head">
        <div>
          <h1>Настройки</h1>
          <p className="tile__note">
            Рабочее пространство целиком: то, что здесь задано, действует на
            все его проекты и книги.
          </p>
        </div>
      </header>

      {workspace.error !== undefined ? (
        <section className="tile">
          <p className="tile__empty">{workspace.error}</p>
        </section>
      ) : (
        <>
          <Models settings={workspace.data} />
          <Sharing settings={workspace.data} />
        </>
      )}

      {settings.error !== undefined ? (
        <section className="tile">
          <p className="tile__empty">{settings.error}</p>
        </section>
      ) : (
        <Notifications settings={settings.data} mine={me?.user.email ?? null} />
      )}
    </>
  );
}
