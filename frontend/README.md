# React + TypeScript + Vite

This template provides a minimal setup to get React working in Vite with HMR and some Oxlint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Oxc](https://oxc.rs)
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/)

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the Oxlint configuration

If you are developing a production application, we recommend enabling type-aware lint rules by installing `oxlint-tsgolint` and editing `.oxlintrc.json`:

```json
{
  "$schema": "./node_modules/oxlint/configuration_schema.json",
  "plugins": ["react", "typescript", "oxc"],
  "options": {
    "typeAware": true
  },
  "rules": {
    "react/rules-of-hooks": "error",
    "react/only-export-components": ["warn", { "allowConstantExport": true }]
  }
}
```

See the [Oxlint rules documentation](https://oxc.rs/docs/guide/usage/linter/rules) for the full list of rules and categories.

## 공통 소스와 검증

`src/lib/api.ts`는 세션 API와 POST SSE 수신을, `types.ts`는 API 데이터 구조를, `format.ts`는 금액·시간·요인 표시를 담당합니다. 직접 관리하는 소스이므로 Git에 포함합니다. 서버용 비밀 키는 이 폴더에 넣지 않습니다.

저장소 루트에서 설치·빌드합니다.

```bash
npm --prefix frontend ci
npm --prefix frontend run build
```

Node.js 24 환경에서는 별도 테스트 의존성 없이 API 클라이언트를 검증할 수 있습니다.

```bash
node --test frontend/tests/api.test.mjs
```
