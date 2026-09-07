"use server";

/* Выход из системы.

   Серверным действием, а не запросом из браузера: у действия проверка
   источника встроена, и отдельный обработчик маршрута для одной кнопки
   заводить незачем.

   Стереть печенья мало. Токен обновления живёт в базе API месяц и после
   «выхода» продолжает открывать сеансы — значит, выход это отзыв на стороне
   API, а очистка браузера лишь его следствие. */

import { redirect } from "next/navigation";

import { apiFetch } from "./api";
import { clearSession, refreshToken } from "./session";

export async function signOut(): Promise<never> {
  const refresh = await refreshToken();

  if (refresh !== undefined) {
    try {
      await apiFetch("/auth/logout", { method: "POST", body: { refresh_token: refresh } });
    } catch {
      // Недоступный API не повод оставить человека внутри: печенья стираем
      // в любом случае, отзыв догонит при следующей попытке обновиться.
    }
  }

  await clearSession();

  redirect("/login");
}
