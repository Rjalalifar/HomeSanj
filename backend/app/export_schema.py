"""Generate JSON Schema and serialized TypeScript wire types from Pydantic."""
import json
from pathlib import Path
from .contracts import Contract, SearchState, PropertyListing, ParseOutput, Itinerary


class Contracts(Contract):
    state: SearchState
    property: PropertyListing
    parser_output: ParseOutput
    itinerary: Itinerary


def ts_type(node):
    if '$ref' in node:
        return node['$ref'].split('/')[-1]
    if 'const' in node:
        return json.dumps(node['const'], ensure_ascii=False)
    if 'enum' in node:
        return ' | '.join(json.dumps(x, ensure_ascii=False) for x in node['enum'])
    if 'anyOf' in node:
        return ' | '.join(ts_type(x) for x in node['anyOf'])
    kind = node.get('type')
    if kind == 'array':
        return f'Array<{ts_type(node.get("items", {}))}>'
    if kind == 'object':
        properties = node.get('properties')
        if properties is not None:
            return '{ ' + '; '.join(f'{json.dumps(k)}: {ts_type(v)}' for k, v in properties.items()) + ' }'
        additional = node.get('additionalProperties', {})
        return f'Record<string, {ts_type(additional) if isinstance(additional, dict) else "unknown"}>'
    return {'string': 'string', 'number': 'number', 'integer': 'number', 'boolean': 'boolean', 'null': 'null'}.get(kind, 'unknown')


def export_schema():
    schema = Contracts.model_json_schema()
    path = Path('shared/contracts.schema.json')
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding='utf-8')
    target = Path('frontend/src/contracts.generated.ts')
    target.parent.mkdir(parents=True, exist_ok=True)
    header = '// Generated from backend/app/contracts.py. Do not edit.\n// These wire types describe fully serialized models, including defaults.\n'
    target.write_text(header + '\n'.join(f'export type {name} = {ts_type(value)};' for name, value in schema['$defs'].items()) + '\n', encoding='utf-8')
    return str(path)


if __name__ == '__main__':
    print(export_schema())
