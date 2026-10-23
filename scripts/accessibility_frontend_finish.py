from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "frontend/src/PhaseTwoApp.tsx"
source = path.read_text(encoding="utf-8")
source = source.replace("import PhaseTwoMap from './PhaseTwoMap';", "import PhaseTwoMap from './PhaseTwoMap';\nimport AccessibilitySummary from './AccessibilitySummary';")
path.write_text(source, encoding="utf-8")

path = ROOT / "frontend/src/filter.ts"
source = path.read_text(encoding="utf-8")
source = source.replace("  const base={balanced:", """  if (state.sort === 'stop_walk_time_asc' || state.sort === 'stop_distance_asc') {
    const value = (row: ResultRow) => state.sort === 'stop_distance_asc' ? row.accessibility?.straight_line_meters ?? null : row.accessibility?.status === 'ok' ? row.accessibility.walk_duration_seconds : null;
    return [...rows].sort((a, b) => {
      const left = value(a), right = value(b);
      if (left === null && right !== null) return 1;
      if (right === null && left !== null) return -1;
      if (left !== null && right !== null && left !== right) return left - right;
      return a.property.property_id.localeCompare(b.property.property_id, 'en');
    });
  }
  const base={balanced:""")
path.write_text(source, encoding="utf-8")
