/* Куда вернуть человека после входа.

   Значение приходит из адреса, поэтому принимается только свой относительный путь: иначе ссылка вида
   /login?next=//evil.example увела бы вошедшего на чужой сайт. */

export function safeReturnPath(value: string | null | undefined): string | null {
  if (typeof value !== "string" || value === "") {
    return null;
  }

  return value.startsWith("/") && !value.startsWith("//") && !value.startsWith("/\\")
    ? value
    : null;
}
