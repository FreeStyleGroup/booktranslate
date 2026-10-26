/* Поиск блока или объекта по коду в пределах книги.

   Обычная форма, а не клиентский компонент: результат — переход, и Enter
   ведёт туда без единой строки скрипта. Код вида `CH03-B0042` находит
   блок в любой главе и на любой странице, `CH03-FIG001` — объект. */

export function FindBlock({ bookId }: { bookId: string }) {
  return (
    <form className="bk-find" action="/app/find" method="get" role="search">
      <input type="hidden" name="book" value={bookId} />
      <label className="wk-find">
        <span aria-hidden="true">🔍</span>
        <input
          type="search"
          name="code"
          placeholder="CH03-B0042"
          aria-label="Найти блок или объект по коду"
          required
          minLength={6}
          maxLength={40}
          pattern="([Bb][Kk]\d+-)?[Cc][Hh]\d+-([Bb]|[Ff][Ii][Gg]|[Tt][Bb][Ll]|[Ee][Qq]|[Cc][Oo][Dd][Ee])\d+"
          title="Код блока или объекта: CH03-B0042, CH03-FIG001"
          autoComplete="off"
          spellCheck={false}
        />
      </label>
    </form>
  );
}
