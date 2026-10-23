"""Attach internal routes and the independent offline worker to the existing app."""
from pathlib import Path
p = Path('backend/app/main.py')
s = p.read_text(encoding='utf-8')
if 'from .phase3_api import' not in s:
    s = s.replace('from .state_audit import record_change', 'from .state_audit import record_change\nfrom .phase3_api import install_phase3')
    s = s.replace('        yield\n        await phase2.stop()', "        offline_task = asyncio.create_task(offline_worker.run()) if start_worker else None\n        yield\n        offline_worker.stopped = True\n        if offline_task:\n            offline_task.cancel()\n            await asyncio.gather(offline_task, return_exceptions=True)\n        await phase2.stop()")
    s = s.replace('    frontend = Path(\'frontend/dist\')', "    offline_worker = install_phase3(app, db, provider)\n\n    frontend = Path('frontend/dist')")
p.write_text(s, encoding='utf-8')
