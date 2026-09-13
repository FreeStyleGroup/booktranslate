/* Страница входа и страница регистрации — одна сборка на оба случая и на
   оба языка.
 *
 * Различаются они подписями и тем, куда ведёт ссылка внизу: со входа — на
 * регистрацию, с регистрации — на вход. Разводить ради этого две почти
 * одинаковые страницы значит однажды поправить одну и забыть вторую. */

import { AuthForm } from "./auth-form";
import { AuthShell } from "./auth-shell";
import { dictionary } from "./i18n";
import { localePath, type Locale } from "./i18n/config";

export function AuthPage({ lang, mode }: { lang: Locale; mode: "login" | "register" }) {
  const t = dictionary(lang);
  const page = mode === "login" ? t.login : t.register;

  return (
    <AuthShell
      lang={lang}
      path={mode === "login" ? "/login" : "/register"}
      title={page.title}
      lead={page.lead}
      footer={{
        text: page.footerText,
        href: localePath(lang, mode === "login" ? "/register" : "/login"),
        link: page.footerLink,
      }}
    >
      <AuthForm
        mode={mode}
        texts={{
          form: t.form,
          submit: page.submit,
          sent:
            mode === "register" ? { title: t.register.sentTitle, text: t.register.sentText } : null,
        }}
      />
    </AuthShell>
  );
}
