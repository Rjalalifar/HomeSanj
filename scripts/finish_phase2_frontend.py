"""Apply the phase-two entry switch and wire-contract corrections."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
entry = root / 'frontend/src/main.tsx'
entry.write_text(entry.read_text(encoding='utf-8').replace("import './style.css';\n", '').replace("import App from './App';", "import App from './PhaseTwoApp';"), encoding='utf-8')
app = root / 'frontend/src/PhaseTwoApp.tsx'
app.write_text(app.read_text(encoding='utf-8').replace('Destination, Itinerary, PatchOperation, SearchState', 'Destination, Itinerary, SearchState').replace("'comparison_added'", "'comparison_opened'").replace("'property_clicked'", "'result_clicked'"), encoding='utf-8')
