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

export function ThemeToggle() {
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

  return (
    <button className="cab__icon" type="button" onClick={toggle} aria-label="Сменить тему">
      <span className="theme-light" aria-hidden="true">
        🌙
      </span>
      <span className="theme-dark" aria-hidden="true">
        ☀️
      </span>
    </button>
  );
}
