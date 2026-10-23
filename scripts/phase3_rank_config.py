"""Expose one bounded evaluation variable through the existing ranker."""
from pathlib import Path
p = Path('backend/app/ranking.py')
s = p.read_text(encoding='utf-8')
s = s.replace('def policy(state):\n', 'def policy(state, config=None):\n')
s = s.replace('    weights = list(WEIGHTS[state.preference])\n', "    weights = list(WEIGHTS[state.preference])\n    multiplier = (config or {}).get('rent_weight_multiplier', 1.0)\n    if set(config or {}) - {'rent_weight_multiplier'} or not isinstance(multiplier, (int, float)) or not 0.1 <= multiplier <= 4:\n        raise ValueError('Unsupported ranking configuration')\n    weights[0] *= multiplier\n")
s = s.replace("return {'version': RANKER_VERSION,", "return {'version': RANKER_VERSION, 'configuration': config or {},")
s = s.replace('def rank_rows(rows, state, semantic_ids=None):\n    ranking = policy(state)', 'def rank_rows(rows, state, semantic_ids=None, config=None):\n    ranking = policy(state, config)')
p.write_text(s, encoding='utf-8')
