"use client";

/* Переключатель темы.

   Выбор хранится у пользователя, а не в организации: за одним заказом
   сидят и в светлом кабинете днём, и в тёмном вечером. Пока выбора нет,
   действует системная настройка — поэтому третьего состояния «как в
   системе» здесь нет: оно и есть исходное.

   Состояния в React у кнопки нет намеренно. Тема живёт атрибутом на
   документе, значок выбирается стилями по тому же атрибуту, а на сервере
   ни того, ни другого не видно — значит и расходиться разметке не с чем. */

const STORAGE_KEY = "bt-theme";

/* Класс кнопки задаётся снаружи: в кабинете это квадратная иконка в
   панели, на главной — круглая в стеклянной полосе. Поведение и значки
   при этом одни, и расходиться им негде. */
export function ThemeToggle({ className = "cab__icon" }: { className?: string }) {
  function toggle(): void {
    const root = document.documentElement;
    const current = root.dataset.theme;
    const dark =
      current === undefined
        ? window.matchMedia("(prefers-color-scheme: dark)").matches
        : current === "dark";

    const next = dark ? "light" : "dark";

    root.dataset.theme = next;

    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Запрет на хранение (приватный режим, настройки браузера) не должен
      // ломать переключение: тема просто не переживёт перезагрузку.
    }
  }

  // Значки рисуются, а не берутся эмодзи: у эмодзи свой цвет, и жёлтый
  // месяц посреди серой панели читается как посторонний предмет. Контур
  // наследует цвет кнопки и живёт по её же правилам наведения.
  return (
    <button className={className} type="button" onClick={toggle} aria-label="Сменить тему">
      <svg className="theme-light" viewBox="0 0 24 24" aria-hidden="true">
        <path
          d="M20.4 14.3A8.6 8.6 0 0 1 9.7 3.6a8.6 8.6 0 1 0 10.7 10.7Z"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinejoin="round"
        />
      </svg>

      <svg className="theme-dark" viewBox="0 0 24 24" aria-hidden="true">
        <g fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
          <circle cx="12" cy="12" r="4.2" />
          <path d="M12 2.4v2.2M12 19.4v2.2M2.4 12h2.2M19.4 12h2.2M5.2 5.2l1.6 1.6M17.2 17.2l1.6 1.6M18.8 5.2l-1.6 1.6M6.8 17.2l-1.6 1.6" />
        </g>
      </svg>
    </button>
  );
}
