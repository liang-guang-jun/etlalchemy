import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { bindAccessToken } from '@/shared/api/client';
import { useSessionStore } from '@/entities/session';
import { App } from '@/app/App';
import '@/app/styles/index.css';

// The shared HTTP client never imports the session entity, so the token getter
// is registered here, once, before the first request can happen.
bindAccessToken(() => useSessionStore.getState().accessToken);

const container = document.getElementById('root');
if (container === null) {
  throw new Error('root element is missing from index.html');
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
