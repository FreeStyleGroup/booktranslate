/* Данные работы: проекты, документы, сегменты.

   Типы описаны здесь, а не рядом с каждой страницей: один и тот же
   документ показывают список, карточка и обзор, и три описания одного
   ответа разъедутся на первой же правке API.

   Загрузка тоже общая. Каждая страница кабинета делает одно и то же:
   берёт токен, спрашивает API, а на отказ по токену уходит на продление
   сеанса. Повторённое на пяти страницах, это правило однажды будет
   забыто на шестой — и та покажет пустой экран вошедшему человеку. */

import { redirect } from "next/navigation";

import { apiFetch, unauthorized } from "./api";
import { accessToken, organizationId, renewUrl } from "./session";

export type Project = {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  source_language: string;
  target_language: string;
  created_at: string;
  updated_at: string;
};

export type DocumentStatus =
  | "uploaded"
  | "parsing"
  | "parsed"
  | "translating"
  | "review"
  | "done"
  | "failed";

export type Document = {
  id: string;
  project_id: string;
  title: string;
  original_filename: string | null;
  source_format: string;
  status: DocumentStatus;
  size_bytes: number | null;
  content_hash: string | null;
  error: string | null;
  input_tokens: number;
  output_tokens: number;
  cached_input_tokens: number;
  cache_write_tokens: number;
  translated_by: string | null;
  created_at: string;
  updated_at: string;
};

export type DocumentProfile = {
  segments: number;
  characters: number;
  words: number;
  longest_segment_chars: number;
  by_kind: Record<string, number>;
  by_status: Record<string, number>;
  untranslated: number;
  unique_untranslated: number;
  repeated: number;
  memory_matches: number;
  terms_total: number;
  undecided_terms: number;
  billable_texts: number;
  billable_characters: number;
  estimate: { input_tokens: number; output_tokens: number; usd: number | null } | null;
};

export type Segment = {
  id: string;
  position: number;
  kind: string;
  status: string;
  source_text: string;
  target_text: string | null;
  source_location: Record<string, unknown> | null;
  quality: { findings?: { check: string; message: string }[] } | null;
  quality_score: number | null;
  translation_source: string | null;
};

export type SegmentPage = {
  total: number;
  limit: number;
  offset: number;
  items: Segment[];
};

/** Ответ API — или причина, по которой его нет.
 *
 * Отказ возвращается страницей, а не бросается: недоступный API это не
 * «страница сломалась», а «сейчас не показать», и человеку надо сказать
 * именно это. Исключение — истёкший сеанс: он уводит на продление, потому
 * что показывать вошедшему сообщение об ошибке вместо его данных нечестно.
 */
export type Loaded<T> = { data: T; error?: undefined } | { data?: undefined; error: string };

export async function load<T>(path: string, returnTo: string): Promise<Loaded<T>> {
  const token = await accessToken();

  if (token === undefined) {
    redirect("/login");
  }

  try {
    return { data: await apiFetch<T>(path, { token, organizationId: await organizationId() }) };
  } catch (error) {
    if (unauthorized(error)) {
      redirect(renewUrl(returnTo));
    }

    return { error: error instanceof Error ? error.message : "Сервис недоступен" };
  }
}
