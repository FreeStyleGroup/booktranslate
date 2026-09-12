/* Запросы администратора площадки — для серверных страниц раздела.

   То же правило, что у кабинета (`lib/work.ts`): истёкший сеанс уводит
   на продление, а недоступный API возвращается страницей словами, а не
   экраном ошибки — администратор должен видеть, что дело в связи, а не в
   его правах. */

import { redirect } from "next/navigation";

import { apiFetch, unauthorized } from "../lib/api";
import { accessToken, renewUrl } from "../lib/session";

export type Loaded<T> = { data: T; error?: undefined } | { data?: undefined; error: string };

export async function adminLoad<T>(path: string, returnTo: string): Promise<Loaded<T>> {
  try {
    return { data: await apiFetch<T>(path, { token: await accessToken() }) };
  } catch (error) {
    if (unauthorized(error)) {
      redirect(renewUrl(returnTo));
    }

    return { error: error instanceof Error ? error.message : "Сервис недоступен" };
  }
}

export function moment(value: string | null): string {
  if (value === null) {
    return "—";
  }

  return new Date(value).toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
