import js from '@eslint/js';
import prettier from 'eslint-config-prettier';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
import tseslint from 'typescript-eslint';

/**
 * Feature-Sliced Design layers, strongest first. A layer may only import the
 * layers below it. Cross-slice imports are expressed with the `@/` alias, so
 * the core `no-restricted-imports` rule can enforce the direction without
 * relying on a module resolver: a slice imports its own files relatively.
 */
const FORBIDDEN_IMPORTS = {
  shared: ['@/app/*', '@/pages/*', '@/widgets/*', '@/features/*', '@/entities/*'],
  entities: ['@/app/*', '@/pages/*', '@/widgets/*', '@/features/*', '@/entities/*'],
  features: ['@/app/*', '@/pages/*', '@/widgets/*', '@/features/*'],
  widgets: ['@/app/*', '@/pages/*', '@/widgets/*'],
  pages: ['@/app/*', '@/pages/*'],
};

const LAYER_CONFIGS = Object.entries(FORBIDDEN_IMPORTS).map(([layer, patterns]) => ({
  files: [`src/${layer}/**/*.{ts,tsx}`],
  rules: {
    'no-restricted-imports': [
      'error',
      {
        patterns: [
          {
            group: patterns,
            message:
              'Feature-Sliced Design: import only from lower layers (app > pages > widgets > features > entities > shared), and never from the same layer.',
          },
        ],
      },
    ],
  },
}));

export default tseslint.config(
  {
    ignores: [
      'dist/**',
      'coverage/**',
      'node_modules/**',
      'playwright-report/**',
      'test-results/**',
      'src/test/**',
      'e2e/**',
    ],
  },
  js.configs.recommended,
  tseslint.configs.recommended,
  {
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
    },
    rules: {
      // TypeScript already resolves identifiers and unused declarations.
      'no-undef': 'off',
      'no-unused-vars': 'off',
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
    },
  },
  {
    files: ['src/**/*.{ts,tsx}'],
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
    },
  },
  ...LAYER_CONFIGS,
  prettier,
);
