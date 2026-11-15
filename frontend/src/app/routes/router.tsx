import { Navigate, createBrowserRouter } from 'react-router';

import { AppShell } from '@/app/layouts/AppShell';
import { AuthLayout } from '@/app/layouts/AuthLayout';
import { CatalogLayout } from '@/app/layouts/CatalogLayout';
import { IngestionLayout } from '@/app/layouts/IngestionLayout';
import { SemanticLayout } from '@/app/layouts/SemanticLayout';
import { SemanticWorkspaceLayout } from '@/app/layouts/SemanticWorkspaceLayout';
import { VocabularyLayout } from '@/app/layouts/VocabularyLayout';
import { WorkspaceLayout } from '@/app/layouts/WorkspaceLayout';
import { RequireAdmin, RequireAuth } from '@/app/routes/guards';
import { lazyPage } from '@/app/routes/lazy';

/** Route table of the application. */
export const router = createBrowserRouter([
  {
    element: <AuthLayout />,
    children: [
      {
        path: '/login',
        element: lazyPage(() => import('@/pages/login/page')),
      },
      {
        path: '/bootstrap',
        element: lazyPage(() => import('@/pages/bootstrap/page')),
      },
    ],
  },
  {
    path: '/',
    element: (
      <RequireAuth>
        <AppShell />
      </RequireAuth>
    ),
    children: [
      { index: true, element: <Navigate to="/catalog" replace /> },
      {
        path: 'catalog',
        element: <CatalogLayout />,
        children: [
          { index: true, element: lazyPage(() => import('@/pages/catalog-list/page')) },
          {
            path: ':catalogId',
            element: lazyPage(() => import('@/pages/catalog-detail/page')),
          },
          {
            path: ':catalogId/schemas/:schema',
            element: lazyPage(() => import('@/pages/schema-detail/page')),
          },
          {
            path: ':catalogId/schemas/:schema/tables/:table',
            element: lazyPage(() => import('@/pages/table-detail/page')),
          },
          {
            path: ':catalogId/schemas/:schema/tables/:table/columns/:column',
            element: lazyPage(() => import('@/pages/column-detail/page')),
          },
        ],
      },
      {
        path: 'semantic',
        element: <SemanticLayout />,
        children: [{ index: true, element: lazyPage(() => import('@/pages/semantic-list/page')) }],
      },
      {
        path: 'semantic/:modelId',
        element: <SemanticWorkspaceLayout />,
        children: [
          { index: true, element: lazyPage(() => import('@/pages/semantic-workspace/page')) },
        ],
      },
      {
        path: 'vocabulary',
        element: <VocabularyLayout />,
        children: [
          { index: true, element: lazyPage(() => import('@/pages/vocabulary-list/page')) },
          {
            path: ':domainId',
            element: lazyPage(() => import('@/pages/vocabulary-domain/page')),
          },
          {
            path: ':domainId/terms/:termId',
            element: lazyPage(() => import('@/pages/term-detail/page')),
          },
        ],
      },
      {
        path: 'ingestion',
        element: <IngestionLayout />,
        children: [
          { index: true, element: lazyPage(() => import('@/pages/ingestion-list/page')) },
          {
            path: ':connectionId',
            element: lazyPage(() => import('@/pages/ingestion-detail/page')),
          },
        ],
      },
      // The wizard is a workspace of its own: its explorer and selection panes
      // scroll inside the card, so the frame must not scroll as a page.
      {
        path: 'ingestion/:connectionId/new-import',
        element: <WorkspaceLayout />,
        children: [{ index: true, element: lazyPage(() => import('@/pages/import-wizard/page')) }],
      },
      {
        path: 'iam/users',
        element: <RequireAdmin>{lazyPage(() => import('@/pages/iam-users/page'))}</RequireAdmin>,
      },
      {
        path: 'agent',
        element: lazyPage(() => import('@/pages/agent/page')),
      },
      {
        path: 'agent/:conversationId',
        element: lazyPage(() => import('@/pages/agent/page')),
      },
    ],
  },
  {
    path: '/error',
    element: lazyPage(() => import('@/pages/error/page')),
  },
  {
    path: '*',
    element: lazyPage(() => import('@/pages/not-found/page')),
  },
]);
