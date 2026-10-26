/* Адреса страниц со списками.

   Отбор, порядок и номер страницы живут в адресе, а не в состоянии
   браузера. Так страница со списком остаётся ссылкой: её можно отправить
   коллеге, оставить в закладках и открыть заново тем же видом — и она же
   открывается на сервере, без ожидания скрипта.

   Собирается адрес одной функцией, потому что собирают его двое —
   заголовки столбцов и переход по страницам, — и разойдясь, они начнут
   терять чужие параметры: сортировка сбросит отбор по проекту. */

/** Значение параметра: `null` убирает его из адреса. */
export type Change = string | number | null;

export function linkTo(
  path: string,
  current: URLSearchParams,
  changes: Record<string, Change>,
): string {
  const next = new URLSearchParams(current);

  for (const [key, value] of Object.entries(changes)) {
    if (value === null) {
      next.delete(key);
    } else {
      next.set(key, String(value));
    }
  }

  const query = next.toString();

  return query === "" ? path : `${path}?${query}`;
}

/** Параметры адреса из того, что Next отдал странице.
 *
 * `searchParams` приходит записью, где значение бывает и массивом — один
 * и тот же ключ в адресе можно повторить. Для списков это всегда ошибка
 * или подбор руками, и берётся первое значение: иначе `sort=title&sort=id`
 * ушло бы в запрос двумя значениями сразу.
 */
export function paramsOf(source: Record<string, string | string[] | undefined>): URLSearchParams {
  const params = new URLSearchParams();

  for (const [key, value] of Object.entries(source)) {
    if (typeof value === "string") {
      params.set(key, value);
    } else if (Array.isArray(value) && value[0] !== undefined) {
      params.set(key, value[0]);
    }
  }

  return params;
}

/** Одно значение из разрешённого набора — или значение по умолчанию.
 *
 * Параметр из адреса уходит в запрос к API. Непроверенный, он отправил бы
 * туда что угодно: прав это не добавляет, но получать 422 из-за подобранной
 * ссылки человек не должен — он увидит сломанную страницу там, где просто
 * опечатался в адресе.
 */
export function oneOf<T extends string>(
  value: string | null,
  allowed: readonly T[],
  fallback: T,
): T {
  return allowed.find((item) => item === value) ?? fallback;
}

/** Неотрицательное целое из адреса: смещение страницы и её размер. */
export function wholeNumber(value: string | null, fallback: number, max: number): number {
  const parsed = Number(value);

  if (!Number.isInteger(parsed) || parsed < 0 || parsed > max) {
    return fallback;
  }

  return parsed;
}
