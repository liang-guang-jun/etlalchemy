import { zodResolver } from '@hookform/resolvers/zod';
import { Plug, ShieldCheck } from 'lucide-react';
import { useForm } from 'react-hook-form';
import { z } from 'zod';

import {
  useSourceKinds,
  useSourceProfiles,
  type Connection,
  type ConnectionCreate,
} from '@/entities/ingestion';
import { normalizeError } from '@/shared/api/error';
import { Button, ConfirmDialog, Dialog, Input, Select } from '@/shared/ui';

import {
  useChangeConnection,
  useCreateConnection,
  useDiscardConnection,
  useRotateCredential,
  useTestConnection,
} from '../api/mutation';

const createSchema = z
  .object({
    name: z.string().min(1, 'Enter a name'),
    kind: z.string().min(1, 'Choose a source kind'),
    endpoint: z.string(),
    defaultCatalog: z.string(),
    database: z.string(),
    username: z.string(),
    profile: z.string(),
    credentialRef: z.string(),
    token: z.string(),
  })
  .superRefine((values, ctx) => {
    const credentials = [values.profile, values.credentialRef, values.token].filter(
      (value) => value.trim() !== '',
    );
    if (credentials.length !== 1) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'Provide exactly one of a profile, a secret reference or an inline secret',
        path: ['credentialRef'],
      });
    }
    if (values.endpoint.trim() === '' && values.profile.trim() === '') {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'Enter an endpoint unless a profile supplies the host',
        path: ['endpoint'],
      });
    }
  });

type CreateValues = z.infer<typeof createSchema>;

const editSchema = z.object({
  name: z.string().min(1, 'Enter a name'),
  endpoint: z.string().min(1, 'Enter an endpoint'),
  defaultCatalog: z.string(),
  database: z.string(),
  username: z.string(),
});

type EditValues = z.infer<typeof editSchema>;

const credentialSchema = z
  .object({
    profile: z.string(),
    credentialRef: z.string(),
    token: z.string(),
  })
  .superRefine((values, ctx) => {
    const credentials = [values.profile, values.credentialRef, values.token].filter(
      (value) => value.trim() !== '',
    );
    if (credentials.length !== 1) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'Provide exactly one of a profile, a secret reference or an inline secret',
        path: ['credentialRef'],
      });
    }
  });

type CredentialValues = z.infer<typeof credentialSchema>;

/** Empty credential fields shared by the create and rotate forms. */
const EMPTY_CREDENTIAL = { profile: '', credentialRef: '', token: '' };

/**
 * Builds the kind-specific options of a connection.
 *
 * Empty fields are dropped so the source adapter keeps its own defaults.
 *
 * @param values Form values carrying the database and the user.
 * @param base Options to start from, used when editing.
 * @returns The options to send.
 */
function buildOptions(
  values: { database: string; username: string },
  base: Record<string, string> = {},
): Record<string, string> {
  const options: Record<string, string> = { ...base };
  const database = values.database.trim();
  const username = values.username.trim();
  if (database === '') {
    delete options.database;
  } else {
    options.database = database;
  }
  if (username === '') {
    delete options.user;
  } else {
    options.user = username;
  }
  return options;
}

export interface CreateConnectionDialogProps {
  open: boolean;
  onClose: () => void;
  onCreated?: (connectionId: string) => void;
}

/**
 * Renders the connection creation form.
 *
 * @param props Component props.
 * @returns The dialog element.
 */
export function CreateConnectionDialog({ open, onClose, onCreated }: CreateConnectionDialogProps) {
  const mutation = useCreateConnection();
  const kinds = useSourceKinds();
  const form = useForm<CreateValues>({
    resolver: zodResolver(createSchema),
    defaultValues: {
      name: '',
      kind: 'databricks',
      endpoint: '',
      defaultCatalog: '',
      database: '',
      username: '',
      ...EMPTY_CREDENTIAL,
    },
  });
  const kind = form.watch('kind');
  const sqlSource = kind === 'postgres';
  const profileSource = kind === 'databricks';
  const profiles = useSourceProfiles('databricks', profileSource);
  const profileNames = profiles.data ?? [];

  return (
    <Dialog
      open={open}
      title="New connection"
      description="A connection points at one external source and keeps only a reference to its secret."
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            loading={mutation.isPending}
            onClick={form.handleSubmit((values) => {
              const options = buildOptions(values);
              const profile = values.profile.trim();
              const credentialRef =
                profile === '' ? values.credentialRef.trim() : `profile:${profile}`;
              const body: ConnectionCreate = {
                name: values.name,
                kind: values.kind,
                endpoint: values.endpoint,
                default_catalog: values.defaultCatalog === '' ? undefined : values.defaultCatalog,
                credential_ref: credentialRef === '' ? undefined : credentialRef,
                token: profile === '' && credentialRef === '' ? values.token : undefined,
                options: Object.keys(options).length === 0 ? undefined : options,
              };
              mutation.mutate(body, {
                onSuccess: (connectionId) => {
                  form.reset();
                  onCreated?.(connectionId);
                  onClose();
                },
              });
            })}
          >
            Create
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <label className="block space-y-1">
          <span className="text-sm text-text">Name</span>
          <Input placeholder="warehouse" {...form.register('name')} />
          {form.formState.errors.name !== undefined ? (
            <span className="text-sm text-danger">{form.formState.errors.name.message}</span>
          ) : null}
        </label>
        <label className="block space-y-1">
          <span className="text-sm text-text">Source kind</span>
          <Select
            options={(kinds.data ?? ['databricks', 'postgres']).map((kind) => ({
              value: kind,
              label: kind,
            }))}
            {...form.register('kind')}
          />
        </label>
        {profileSource ? (
          <label className="block space-y-1">
            <span className="text-sm text-text">Databricks CLI profile</span>
            <Input
              list="databricks-profiles"
              placeholder="DEFAULT"
              autoComplete="off"
              {...form.register('profile')}
            />
            <datalist id="databricks-profiles">
              {profileNames.map((profile) => (
                <option key={profile.name} value={profile.name}>
                  {profile.host ?? profile.name}
                </option>
              ))}
            </datalist>
            <span className="block text-xs text-text-disabled">
              Authenticates through the local ~/.databrickscfg profile; no secret is stored.
            </span>
          </label>
        ) : null}
        <label className="block space-y-1">
          <span className="text-sm text-text">Endpoint</span>
          <Input
            placeholder={sqlSource ? 'localhost:5432' : 'https://dbc-1234.cloud.databricks.com'}
            {...form.register('endpoint')}
          />
          {form.formState.errors.endpoint !== undefined ? (
            <span className="text-sm text-danger">{form.formState.errors.endpoint.message}</span>
          ) : profileSource ? (
            <span className="block text-xs text-text-disabled">
              Optional with a profile: the profile host is used when empty.
            </span>
          ) : null}
        </label>
        <label className="block space-y-1">
          <span className="text-sm text-text">Default catalog</span>
          <Input placeholder="main" {...form.register('defaultCatalog')} />
          <span className="block text-xs text-text-disabled">
            {sqlSource
              ? 'Also used as the database name when “Database” is empty.'
              : 'Catalog used when an import does not name one.'}
          </span>
        </label>
        <div className="grid grid-cols-2 gap-3">
          <label className="block space-y-1">
            <span className="text-sm text-text">Database</span>
            <Input
              placeholder={sqlSource ? 'etlalchemy' : 'optional'}
              {...form.register('database')}
            />
          </label>
          <label className="block space-y-1">
            <span className="text-sm text-text">Username</span>
            <Input
              placeholder={sqlSource ? 'postgres' : 'optional'}
              autoComplete="off"
              {...form.register('username')}
            />
          </label>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <label className="block space-y-1">
            <span className="text-sm text-text">Secret reference</span>
            <Input placeholder="env:DBX_TOKEN" {...form.register('credentialRef')} />
          </label>
          <label className="block space-y-1">
            <span className="text-sm text-text">{sqlSource ? 'Password' : 'Inline token'}</span>
            <Input
              type="password"
              autoComplete="new-password"
              placeholder="••••••"
              {...form.register('token')}
            />
          </label>
        </div>
        {form.formState.errors.credentialRef !== undefined ? (
          <p className="text-sm text-danger">{form.formState.errors.credentialRef.message}</p>
        ) : (
          <p className="text-xs text-text-disabled">
            {profileSource
              ? 'Fill exactly one of the three credential fields. The secret is encrypted at rest and never returned again.'
              : 'Fill exactly one of the two credential fields. The secret is encrypted at rest and never returned again.'}
          </p>
        )}
        {mutation.error !== null ? (
          <p className="text-sm text-danger">{normalizeError(mutation.error).detail}</p>
        ) : null}
      </div>
    </Dialog>
  );
}

export interface EditConnectionDialogProps {
  open: boolean;
  connection: Connection;
  onClose: () => void;
}

/**
 * Renders the connection metadata form.
 *
 * @param props Component props.
 * @returns The dialog element.
 */
export function EditConnectionDialog({ open, connection, onClose }: EditConnectionDialogProps) {
  const mutation = useChangeConnection(connection.connection_id);
  const form = useForm<EditValues>({
    resolver: zodResolver(editSchema),
    defaultValues: {
      name: connection.name,
      endpoint: connection.endpoint,
      defaultCatalog: connection.default_catalog ?? '',
      database: connection.options.database ?? '',
      username: connection.options.user ?? '',
    },
  });

  return (
    <Dialog
      open={open}
      title="Edit connection"
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            loading={mutation.isPending}
            onClick={form.handleSubmit((values) => {
              mutation.mutate(
                {
                  name: values.name,
                  endpoint: values.endpoint,
                  default_catalog: values.defaultCatalog,
                  options: buildOptions(values, connection.options),
                },
                { onSuccess: onClose },
              );
            })}
          >
            Save
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <label className="block space-y-1">
          <span className="text-sm text-text">Name</span>
          <Input {...form.register('name')} />
        </label>
        <label className="block space-y-1">
          <span className="text-sm text-text">Endpoint</span>
          <Input {...form.register('endpoint')} />
        </label>
        <label className="block space-y-1">
          <span className="text-sm text-text">Default catalog</span>
          <Input {...form.register('defaultCatalog')} />
        </label>
        <div className="grid grid-cols-2 gap-3">
          <label className="block space-y-1">
            <span className="text-sm text-text">Database</span>
            <Input placeholder="optional" {...form.register('database')} />
          </label>
          <label className="block space-y-1">
            <span className="text-sm text-text">Username</span>
            <Input placeholder="optional" autoComplete="off" {...form.register('username')} />
          </label>
        </div>
        <p className="text-xs text-text-disabled">
          The password is not metadata: use “Rotate credential” to replace it.
        </p>
        {mutation.error !== null ? (
          <p className="text-sm text-danger">{normalizeError(mutation.error).detail}</p>
        ) : null}
      </div>
    </Dialog>
  );
}

export interface RotateCredentialDialogProps {
  open: boolean;
  connectionId: string;
  /** Source kind, used to label the secret as a password for SQL sources. */
  kind?: string;
  onClose: () => void;
}

/**
 * Renders the credential rotation form with an inline connection probe.
 *
 * @param props Component props.
 * @returns The dialog element.
 */
export function RotateCredentialDialog({
  open,
  connectionId,
  kind,
  onClose,
}: RotateCredentialDialogProps) {
  const sqlSource = kind === 'postgres';
  const profileSource = kind === 'databricks';
  const profiles = useSourceProfiles('databricks', profileSource);
  const profileNames = profiles.data ?? [];
  const mutation = useRotateCredential(connectionId);
  const probe = useTestConnection(connectionId);
  const form = useForm<CredentialValues>({
    resolver: zodResolver(credentialSchema),
    defaultValues: EMPTY_CREDENTIAL,
  });

  return (
    <Dialog
      open={open}
      title="Rotate credential"
      description="The previous secret is replaced; the new one is never returned again."
      onClose={onClose}
      footer={
        <>
          <Button
            variant="secondary"
            icon={<Plug className="size-4" aria-hidden="true" />}
            loading={probe.isPending}
            onClick={() => {
              probe.mutate();
            }}
          >
            Test connection
          </Button>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            loading={mutation.isPending}
            onClick={form.handleSubmit((values) => {
              const profile = values.profile.trim();
              const credentialRef =
                profile === '' ? values.credentialRef.trim() : `profile:${profile}`;
              mutation.mutate(
                {
                  credential_ref: credentialRef === '' ? undefined : credentialRef,
                  token: profile === '' && credentialRef === '' ? values.token : undefined,
                },
                { onSuccess: onClose },
              );
            })}
          >
            Save
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        {profileSource ? (
          <label className="block space-y-1">
            <span className="text-sm text-text">Databricks CLI profile</span>
            <Input
              list="databricks-rotate-profiles"
              placeholder="DEFAULT"
              autoComplete="off"
              {...form.register('profile')}
            />
            <datalist id="databricks-rotate-profiles">
              {profileNames.map((profile) => (
                <option key={profile.name} value={profile.name}>
                  {profile.host ?? profile.name}
                </option>
              ))}
            </datalist>
            <span className="block text-xs text-text-disabled">
              Authenticates through the local ~/.databrickscfg profile; no secret is stored.
            </span>
          </label>
        ) : null}
        <label className="block space-y-1">
          <span className="text-sm text-text">Secret reference</span>
          <Input placeholder="env:DBX_TOKEN" {...form.register('credentialRef')} />
        </label>
        <label className="block space-y-1">
          <span className="text-sm text-text">{sqlSource ? 'Password' : 'Inline token'}</span>
          <Input
            type="password"
            autoComplete="new-password"
            placeholder="••••••"
            {...form.register('token')}
          />
        </label>
        {form.formState.errors.credentialRef !== undefined ? (
          <p className="text-sm text-danger">{form.formState.errors.credentialRef.message}</p>
        ) : (
          <p className="flex items-center gap-1.5 text-xs text-text-disabled">
            <ShieldCheck className="size-3.5" aria-hidden="true" />
            {profileSource
              ? 'Fill exactly one of the three credential fields.'
              : 'Fill exactly one of the two credential fields.'}
          </p>
        )}
        {mutation.error !== null ? (
          <p className="text-sm text-danger">{normalizeError(mutation.error).detail}</p>
        ) : null}
      </div>
    </Dialog>
  );
}

export interface DiscardConnectionConfirmProps {
  open: boolean;
  connection: Connection;
  onClose: () => void;
  onDiscarded: () => void;
}

/**
 * Confirms the soft delete of a connection.
 *
 * @param props Component props.
 * @returns The confirmation dialog.
 */
export function DiscardConnectionConfirm({
  open,
  connection,
  onClose,
  onDiscarded,
}: DiscardConnectionConfirmProps) {
  const mutation = useDiscardConnection(connection.connection_id);

  return (
    <ConfirmDialog
      open={open}
      danger
      title="Delete connection"
      description={`Deletes connection "${connection.name}". Its import history stays readable.`}
      confirmLabel="Delete"
      loading={mutation.isPending}
      onCancel={onClose}
      onConfirm={() => {
        mutation.mutate(undefined, { onSuccess: onDiscarded });
      }}
    />
  );
}
