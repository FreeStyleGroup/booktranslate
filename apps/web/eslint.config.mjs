/* eslint-config-next 16 отдаёт готовые flat-конфиги, поэтому FlatCompat
   здесь не нужен — с ним «next/typescript» разворачивается в конфиг с
   круговой ссылкой на плагин react, и ESLint падает ещё до проверки. */
import coreWebVitals from "eslint-config-next/core-web-vitals";
import typescript from "eslint-config-next/typescript";

const config = [
  ...coreWebVitals,
  ...typescript,
  {
    ignores: [".next/**", "node_modules/**", "next-env.d.ts"],
  },
];

export default config;
