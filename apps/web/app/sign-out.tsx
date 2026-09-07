/* Кнопка выхода.

   Общая для кабинета и управления доступом: выход везде значит одно и то
   же, и второй его вариант однажды разошёлся бы с первым. */

import { signOut } from "./lib/session-actions";

export function SignOut({ className }: { className?: string }) {
  return (
    <form action={signOut}>
      <button className={className} type="submit">
        Выйти
      </button>
    </form>
  );
}
