"""Keep serialized test defaults and property accessibility labels current."""
from pathlib import Path

path = Path('frontend/src/phase2.test.ts')
source = path.read_text(encoding='utf-8-sig')
source = source.replace("const defaults: SearchState = { schema_version:", "const defaults: SearchState = { accessibility: null, schema_version:")
path.write_text(source, encoding='utf-8')
path = Path('frontend/src/api.ts')
source = path.read_text(encoding='utf-8-sig').replace('export type AccessibilityStop = {stop_id?', "export type AccessibilityStop = {stop_type?:'metro'|'bus'; stop_id?")
path.write_text(source, encoding='utf-8')
path = Path('frontend/src/AccessibilitySummary.tsx')
source = path.read_text(encoding='utf-8-sig').replace('`نزدیک‌ترین ایستگاه: ${stopName}`', "`نزدیک‌ترین ایستگاه ${stop.stop_type === 'metro' ? 'مترو' : stop.stop_type === 'bus' ? 'اتوبوس' : ''}: ${stopName}`")
path.write_text(source, encoding='utf-8')
print('Updated frontend contract fixture and stop kind label.')
