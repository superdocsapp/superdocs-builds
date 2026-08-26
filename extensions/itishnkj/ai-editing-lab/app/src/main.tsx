import { createRoot } from 'react-dom/client';

import App from './App';
import { ErrorBoundary } from '@/components/error-boundary';

import './index.css';

const mockApiRequested =
  new URLSearchParams(window.location.search).get('mock-api') === '1';
if (import.meta.env.DEV && mockApiRequested) {
  window.sessionStorage.setItem('ai-editing-lab-mock-api', '1');
}
if (
  import.meta.env.DEV &&
  window.sessionStorage.getItem('ai-editing-lab-mock-api') === '1'
) {
  const { installMockLabApi } = await import('./lib/mock-lab-api');
  installMockLabApi();
}

createRoot(document.getElementById('root')!, {
  // Keeps caught errors off reportError(), which would raise the dev overlay.
  onCaughtError: (error, errorInfo) => {
    console.error(error, errorInfo.componentStack);
  },
}).render(
  <ErrorBoundary>
    <App />
  </ErrorBoundary>,
);
