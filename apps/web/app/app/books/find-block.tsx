/* Поиск блока по коду в пределах книги.

   Обычная форма, а не клиентский компонент: результат — переход к блоку,
   и Enter ведёт туда без единой строки скрипта. Код вида `CH03-B0042`
   находит блок в любой главе и на любой странице. */

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
          aria-label="Найти блок по коду"
          required
          minLength={6}
          maxLength={40}
          pattern="([Bb][Kk]\d+-)?[Cc][Hh]\d+-[Bb]\d+"
          title="Код блока: CH03-B0042 или BK01-CH03-B0042"
          autoComplete="off"
          spellCheck={false}
        />
      </label>
    </form>
  );
}
