import { zodResolver } from '@hookform/resolvers/zod';
import { useForm } from 'react-hook-form';

import {
  apiKeyLoginSchema,
  passwordLoginSchema,
  type ApiKeyLogin,
  type PasswordLogin,
} from '@/entities/session';
import { normalizeError } from '@/shared/api/error';
import { Button, Input, Tabs, Textarea, Tooltip } from '@/shared/ui';
import { useState } from 'react';

import { useApiKeyLogin, usePasswordLogin } from '../api/mutation';

type Mode = 'password' | 'api-key' | 'oidc';

const MODES = [
  { value: 'password', label: 'Password' },
  { value: 'api-key', label: 'API Key' },
  { value: 'oidc', label: 'OIDC (host provided)', disabled: true },
];

/**
 * Renders the login form with the password and API key tabs.
 *
 * @returns The login form.
 */
export function LoginForm() {
  const [mode, setMode] = useState<Mode>('password');
  const passwordLogin = usePasswordLogin();
  const apiKeyLogin = useApiKeyLogin();

  const passwordForm = useForm<PasswordLogin>({
    resolver: zodResolver(passwordLoginSchema),
    defaultValues: { login: '', password: '' },
  });
  const apiKeyForm = useForm<ApiKeyLogin>({
    resolver: zodResolver(apiKeyLoginSchema),
    defaultValues: { api_key: '' },
  });

  const error = passwordLogin.error ?? apiKeyLogin.error;

  return (
    <div className="w-full max-w-md space-y-4 rounded-lg border border-border bg-surface p-6 shadow-card">
      <header className="space-y-1">
        <h1 className="text-lg font-semibold text-text">Sign in to ETLAlchemy</h1>
        <p className="text-sm text-text-muted">Sign in with a password or an API key.</p>
      </header>

      <Tabs
        items={MODES}
        value={mode}
        onChange={(value) => {
          setMode(value as Mode);
        }}
      />

      {mode === 'password' ? (
        <form
          className="space-y-3"
          onSubmit={passwordForm.handleSubmit((values) => {
            passwordLogin.mutate(values);
          })}
        >
          <label className="block space-y-1">
            <span className="text-sm text-text">Username or email</span>
            <Input placeholder="admin@example.com" {...passwordForm.register('login')} />
            {passwordForm.formState.errors.login !== undefined ? (
              <span className="text-sm text-danger">
                {passwordForm.formState.errors.login.message}
              </span>
            ) : null}
          </label>
          <label className="block space-y-1">
            <span className="text-sm text-text">Password</span>
            <Input type="password" {...passwordForm.register('password')} />
            {passwordForm.formState.errors.password !== undefined ? (
              <span className="text-sm text-danger">
                {passwordForm.formState.errors.password.message}
              </span>
            ) : null}
          </label>
          <Button type="submit" className="w-full" loading={passwordLogin.isPending}>
            Sign in
          </Button>
        </form>
      ) : null}

      {mode === 'api-key' ? (
        <form
          className="space-y-3"
          onSubmit={apiKeyForm.handleSubmit((values) => {
            apiKeyLogin.mutate(values);
          })}
        >
          <label className="block space-y-1">
            <span className="text-sm text-text">API Key</span>
            <Textarea
              rows={3}
              placeholder="Paste your API key"
              {...apiKeyForm.register('api_key')}
            />
            {apiKeyForm.formState.errors.api_key !== undefined ? (
              <span className="text-sm text-danger">
                {apiKeyForm.formState.errors.api_key.message}
              </span>
            ) : null}
          </label>
          <Button type="submit" className="w-full" loading={apiKeyLogin.isPending}>
            Sign in
          </Button>
        </form>
      ) : null}

      {mode === 'oidc' ? (
        <Tooltip content="The OIDC authorization code flow is handled by the host application; this tab is a placeholder.">
          <p className="text-sm text-text-muted">
            This sign-in method is provided by the host application.
          </p>
        </Tooltip>
      ) : null}

      {error !== null && error !== undefined ? (
        <p role="alert" className="text-sm text-danger">
          {normalizeError(error).detail}
        </p>
      ) : null}
    </div>
  );
}
