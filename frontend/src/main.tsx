import { StrictMode, lazy, Suspense } from 'react';
import { createRoot } from 'react-dom/client';
import 'leaflet/dist/leaflet.css';
import App from './PhaseTwoApp';
const InternalReview = lazy(() => import('./InternalReview'));
createRoot(document.getElementById('root')!).render(<StrictMode><Suspense fallback={<p>در حال بارگذاری…</p>}>{location.pathname === '/internal' ? <InternalReview/> : <App/>}</Suspense></StrictMode>);
