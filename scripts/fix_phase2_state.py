"""Align browser scalar validation and reset behavior with the canonical contract."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
path = root / 'frontend/src/state.ts'
content = path.read_text(encoding='utf-8')
if "from './stateValidation'" not in content:
    content = "import { validateScalarState, clearedState } from './stateValidation';\n" + content
    content = content.replace("if(next.travel.time?.length===5)", "validateScalarState(next);\n  if(next.travel.time?.length===5)")
    content = content.replace("state:{...structuredClone(store.defaults),travel:structuredClone(store.state.travel),preference:store.state.preference,soft_preferences:store.state.soft_preferences,state_revision:store.state.state_revision+1}", "state:clearedState(store.state,store.defaults)")
path.write_text(content, encoding='utf-8')
