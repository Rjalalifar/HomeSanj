"""Use a lazy internal route in the existing React application."""
from pathlib import Path
p = Path('frontend/src/main.tsx')
s = p.read_text(encoding='utf-8')
s = s.replace("import { StrictMode }", "import { StrictMode, lazy, Suspense }")
s = s.replace("createRoot(document.getElementById('root')!).render(<StrictMode><App/></StrictMode>);", "const InternalReview = lazy(() => import('./InternalReview'));\ncreateRoot(document.getElementById('root')!).render(<StrictMode><Suspense fallback={<p>در حال بارگذاری…</p>}>{location.pathname === '/internal' ? <InternalReview/> : <App/>}</Suspense></StrictMode>);")
p.write_text(s, encoding='utf-8')
