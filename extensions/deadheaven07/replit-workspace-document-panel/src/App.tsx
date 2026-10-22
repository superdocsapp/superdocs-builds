import { HandshakeProvider } from '@replit/extensions-react';
import { DocumentPanel } from './components/DocumentPanel';

export function App() {
  return (
    <HandshakeProvider>
      <div className="h-full w-full">
        <DocumentPanel />
      </div>
    </HandshakeProvider>
  );
}