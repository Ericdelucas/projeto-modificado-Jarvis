// Must stay the first import: fills in crypto.randomUUID before any module uses it.
import './lib/polyfills';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router';
import { ErrorBoundary } from './components/ErrorBoundary';
import App from './App';
import { initApiBase } from './lib/api';
import { initAnalytics } from './lib/analytics';
import './index.css';

function applyTheme() {
  document.documentElement.classList.remove('light');
  document.documentElement.classList.add('dark');
}


applyTheme();

// Fetch the API base URL from the Tauri backend before rendering.
// This ensures JARVIS_PORT is defined in one place (the Rust backend).
// In non-Tauri environments this is a no-op.
initApiBase().finally(() => {
  // Kick off analytics init in the background — it's never awaited so
  // a slow/failed identity fetch never delays UI render.
  void initAnalytics();

  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <ErrorBoundary>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </ErrorBoundary>
    </StrictMode>,
  );
});

// A development HUD must not be hidden behind an old production PWA shell.
if (import.meta.env.DEV && 'serviceWorker' in navigator) {
  void navigator.serviceWorker.getRegistrations().then(registrations => {
    for (const registration of registrations) void registration.unregister();
  });
}
