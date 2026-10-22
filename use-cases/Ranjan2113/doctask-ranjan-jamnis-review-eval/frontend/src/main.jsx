import { createRoot } from 'react-dom/client';
import App from './App.jsx';
import './styles.css';

/**
 * StrictMode is deliberately NOT used here.
 *
 * In development React 18's StrictMode mounts, unmounts and remounts every
 * component, which recreates the DecisionClock held in a ref and restarts the
 * interval for every visible change. The reset happens within the same tick,
 * so the distortion is small -- but this app is a measurement instrument, its
 * output is decision time, and reviewers run it against the dev server. A
 * known source of timing noise is not worth the extra dev-time warnings.
 */
createRoot(document.getElementById('root')).render(<App />);
