/* Кто вошёл — для серверных компонентов.

   Обёрнуто в `cache`: раскладка и страница кабинета собираются в одном
   запросе и обе спрашивают одно и то же, а два обращения к `/auth/me` за
   одну отрисовку — лишняя нагрузка и лишний шанс разойтись.

   Отказ API при живом печенье — не «гость», а сеанс, который кончился
   раньше печенья: администратор закрыл доступ, или доступ истёк за секунду
   до клика. Показать на такое демонстрацию значит соврать; вместо этого
   страница уходит на маршрут продления, который либо выдаст новый токен,
   либо честно выведет ко входу. Прочие сбои (API не поднят) остаются
   «гостем»: страница покажет, что сможет. */

import { redirect } from "next/navigation";
import { cache } from "react";

import { apiFetch, unauthorized, type CurrentUser } from "./api";
import { accessToken, renewUrl } from "./session";

export const currentUser = cache(async (returnTo: string): Promise<CurrentUser | null> => {
  const token = await accessToken();

  if (token === undefined) {
    return null;
  }

  try {
    return await apiFetch<CurrentUser>("/auth/me", { token });
  } catch (error) {
    if (unauthorized(error)) {
      redirect(renewUrl(returnTo));
    }

    return null;
  }
});
