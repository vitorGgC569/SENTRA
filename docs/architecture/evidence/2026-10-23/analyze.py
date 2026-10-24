"""Read tracked source without importing application modules or running them."""
from __future__ import annotations
import ast
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else '.').resolve()
OUT = ROOT / 'docs/architecture/evidence/2026-10-23'
paths = [p.decode('utf-8') for p in subprocess.check_output(
    ['git', 'ls-files', '-z'], cwd=ROOT).split(b'\0') if p]
paths = [p for p in paths if (ROOT / p).is_file()]
code_extensions = {'.py', '.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs', '.css', '.ps1'}
first_party_roots = {p.split('/')[0] for p in paths if p.startswith('sentra_')}
first_party_roots |= {'orchestrator', 'browser', 'native_bridge', 'sandbox_runtime',
                      'self_improvement', 'local_model', 'dashboard', 'edge_extension'}
records, texts, trees, py_modules, parse_errors = [], {}, {}, {}, []
for name in paths:
    p = ROOT / name
    if p.suffix not in code_extensions:
        continue
    if name.startswith(('vendor/', 'third_party/')):
        continue
    source = p.read_text(encoding='utf-8-sig', errors='replace')
    root = name.split('/')[0]
    generated = '/static/desktop-assets/' in name or '.min.' in name
    vendored = '/vendor/' in name or '/third_party/' in name
    role = ('test' if root == 'tests' or '/test/' in name or '/tests/' in name
            else 'vendor' if vendored
            else 'generated' if generated else 'first_party' if root in first_party_roots
            else 'integration' if root == 'integrations' else 'tooling_or_other')
    record = {'path': name, 'root': root, 'role': role, 'extension': p.suffix,
              'lines': len(source.splitlines()), 'bytes': p.stat().st_size,
              'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
    if p.suffix == '.py':
        try:
            tree = ast.parse(source, filename=name)
            trees[name] = tree
            module = name[:-3].replace('/', '.')
            if module.endswith('.__init__'):
                module = module[:-9]
            py_modules[module] = name
            record['functions'] = sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in ast.walk(tree))
            record['classes'] = sum(isinstance(n, ast.ClassDef) for n in ast.walk(tree))
        except SyntaxError as err:
            parse_errors.append({'path': name, 'line': err.lineno, 'message': err.msg})
    if name.startswith('sentra_canvas/desktop_ui/src/') and p.suffix in {'.jsx', '.js', '.css'}:
        record['useState_calls_textual'] = len(re.findall(r'\buseState\s*\(', source))
        record['useEffect_calls_textual'] = len(re.findall(r'\buseEffect\s*\(', source))
        record['css_imports'] = re.findall(r"import\s+['\"]([^'\"]+\.css)['\"]", source)
    records.append(record)
    texts[name] = source

imports = []
class ImportVisitor(ast.NodeVisitor):
    def __init__(self, name):
        self.name = name
        self.function_depth = 0
        self.type_only = 0
        self.package = name[:-3].replace('/', '.')
        if self.package.endswith('.__init__'):
            self.package = self.package[:-9]
        else:
            self.package = self.package.rsplit('.', 1)[0] if '.' in self.package else ''
    def visit_FunctionDef(self, node):
        self.function_depth += 1
        self.generic_visit(node)
        self.function_depth -= 1
    visit_AsyncFunctionDef = visit_FunctionDef
    def visit_If(self, node):
        is_types = isinstance(node.test, ast.Name) and node.test.id == 'TYPE_CHECKING'
        if is_types:
            self.type_only += 1
        self.generic_visit(node)
        if is_types:
            self.type_only -= 1
    def add(self, module, line):
        if module not in py_modules:
            return
        target = py_modules[module]
        if target == self.name:
            return
        imports.append({'source': self.name, 'target': target, 'line': line,
                        'deferred': self.function_depth > 0, 'type_only': self.type_only > 0})
    def visit_Import(self, node):
        for item in node.names:
            self.add(item.name, node.lineno)
    def visit_ImportFrom(self, node):
        if node.level:
            chunks = self.package.split('.') if self.package else []
            prefix = chunks[:len(chunks) - node.level + 1]
            base = '.'.join(prefix + ([node.module] if node.module else []))
        else:
            base = node.module or ''
        for item in node.names:
            candidate = base + '.' + item.name if base else item.name
            self.add(candidate if candidate in py_modules else base, node.lineno)

for name, tree in trees.items():
    ImportVisitor(name).visit(tree)

imports = list({(i['source'], i['target'], i['line'], i['deferred'], i['type_only']): i
                for i in imports}.values())

runtime_imports = [i for i in imports if i['source'].split('/')[0] in first_party_roots
                   and i['target'].split('/')[0] in first_party_roots and not i['type_only']]
edges = defaultdict(list)
for item in runtime_imports:
    a, b = item['source'].split('/')[0], item['target'].split('/')[0]
    if a != b:
        edges[a, b].append(item)
package_edges = [{'source': a, 'target': b, 'import_sites': len(sites),
                  'deferred_sites': sum(s['deferred'] for s in sites),
                  'examples': sites[:4]} for (a, b), sites in sorted(edges.items())]

def scc(graph):
    result, stack, on_stack, index, low, counter = [], [], set(), {}, {}, 0
    def visit(v):
        nonlocal counter
        index[v] = low[v] = counter
        counter += 1
        stack.append(v)
        on_stack.add(v)
        for w in graph.get(v, set()):
            if w not in index:
                visit(w)
                low[v] = min(low[v], low[w])
            elif w in on_stack:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            component = []
            while True:
                w = stack.pop()
                on_stack.remove(w)
                component.append(w)
                if w == v:
                    break
            if len(component) > 1:
                result.append(sorted(component))
    for v in list(graph):
        if v not in index:
            visit(v)
    return sorted(result, key=len, reverse=True)

package_graph = defaultdict(set)
module_graph = defaultdict(set)
for item in runtime_imports:
    a, b = item['source'], item['target']
    module_graph[a].add(b)
    if a.split('/')[0] != b.split('/')[0]:
        package_graph[a.split('/')[0]].add(b.split('/')[0])

by_root = defaultdict(lambda: {'files': 0, 'lines': 0, 'bytes': 0})
for r in records:
    if r['role'] not in {'generated', 'test', 'vendor'}:
        for key in ['lines', 'bytes']:
            by_root[r['root']][key] += r[key]
        by_root[r['root']]['files'] += 1
manifests = []
for name in paths:
    if Path(name).name != 'package.json' or name.startswith(('vendor/', 'third_party/')):
        continue
    value = json.loads((ROOT / name).read_text(encoding='utf-8-sig'))
    manifests.append({'path': name, 'name': value.get('name'), 'scripts': value.get('scripts', {}),
                      'runtime_dependencies': len(value.get('dependencies', {})),
                      'dev_dependencies': len(value.get('devDependencies', {})),
                      'has_lock': (ROOT / name).with_name('package-lock.json').is_file()})

result = {'scope': 'Tracked files read from current working tree, not immutable HEAD; no application modules imported.',
          'limitations': ['Line counts are physical, not executable LOC.',
                         'Python imports are static; dynamic imports and JS dependency cycles are not modeled.',
                         'Imports inside functions retained as deferred; TYPE_CHECKING-only imports excluded from runtime graph.',
                         'SCCs describe static coupling, not proven runtime import errors.',
                         'Submodules, untracked files and ignored dependencies excluded from metrics.'],
          'tracked_files': len(paths), 'code_files_measured': len(records),
          'files_by_role': dict(Counter(r['role'] for r in records)),
          'roots': dict(sorted(by_root.items(), key=lambda item: item[1]['lines'], reverse=True)),
          'largest_first_party': sorted((r for r in records if r['role'] == 'first_party'),key=lambda r:r['lines'],reverse=True)[:30],
          'frontend_flat_source_files': sum('/' not in r['path'].removeprefix('sentra_canvas/desktop_ui/src/') for r in records if r['path'].startswith('sentra_canvas/desktop_ui/src/')),
          'frontend_total_source_files': sum(r['path'].startswith('sentra_canvas/desktop_ui/src/') for r in records),
          'python_parse_errors': parse_errors, 'package_edges': package_edges,
          'python_package_sccs': scc(package_graph), 'python_module_sccs': scc(module_graph),
          'node_projects': manifests, 'files': records}
OUT.mkdir(parents=True, exist_ok=True)
(OUT / 'structure.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:v for k,v in result.items() if k not in {'files','package_edges','largest_first_party','node_projects','python_module_sccs'}}, ensure_ascii=False, indent=2))
print('LARGEST', json.dumps([(r['path'],r['lines']) for r in result['largest_first_party'][:12]],ensure_ascii=False))
print('NODE PROJECTS', json.dumps([m['path'] for m in manifests]))
