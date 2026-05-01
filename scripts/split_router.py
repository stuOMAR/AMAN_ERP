"""Generic router splitter for T6.3 (file ≤ 1500 lines DoD).

Usage:
    python scripts/split_router.py <router_file> <bucket_config_json>

Where bucket_config_json is a JSON file like:
    {
      "package_init": {
        "prefix": "/projects",
        "tags": ["Projects"],
        "module_guard": "projects"
      },
      "header_imports": "<raw text inserted into each sub-file's header>",
      "buckets_url": {
          "tasks": ["tasks", "task-dependencies"],
          ...
      },
      "buckets_helper": {
          "_dec": "core",
          "ProjectCreate": "core",
          ...
      }
    }

Splits the router file into routers/<base>/<bucket>.py + __init__.py aggregator.
Algorithm: detect top-level @router decorators and standalone def/class blocks,
bucket each by URL prefix or helper-name, write sub-files with a generated
header. Original .py file is then deleted.
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import defaultdict


def detect_blocks(lines):
    """Return list of (start_idx, end_idx, kind, key) blocks.

    Block start = top-level @router decorator OR top-level def/class with no
    @router decorator above it. The header (everything before the first block)
    is treated as `lines[:block_starts[0]]`.
    """
    block_starts = []
    for i, ln in enumerate(lines):
        s = ln.rstrip()
        if s.startswith('@router.'):
            block_starts.append(i)
        elif s.startswith(('def ', 'class ', 'async def ')):
            j = i - 1
            is_route = False
            while j >= 0:
                raw = lines[j]
                ps = raw.rstrip()
                if ps.startswith('@'):
                    is_route = True
                    break
                if ps == '':
                    j -= 1
                    continue
                # Continuation of a multi-line decorator? line starts
                # with whitespace (indented) AND we haven't hit a non-
                # decorator top-level statement yet.
                if raw[:1] in (' ', '\t'):
                    j -= 1
                    continue
                break
            if not is_route:
                block_starts.append(i)
    n = len(lines)
    blocks = []
    for k, start in enumerate(block_starts):
        end = block_starts[k + 1] if k + 1 < len(block_starts) else n
        m_route = None
        for j in range(start, min(end, start + 10)):
            mr = re.match(r'@router\.\w+\(\s*"([^"]*)"', lines[j])
            if mr:
                m_route = mr
                break
        if m_route:
            blocks.append((start, end, 'route', m_route.group(1)))
        else:
            ms = re.match(r'^(?:async\s+)?(def|class)\s+(\w+)', lines[start])
            if ms:
                blocks.append((start, end, ms.group(1), ms.group(2)))
            else:
                blocks.append((start, end, 'unknown', f'line{start+1}'))
    return block_starts, blocks


def bucket_route(path: str, buckets_url: dict, default: str = 'core') -> str:
    """Map URL path -> bucket name. Recognises /{...}/seg and /seg/... patterns."""
    parts = [p for p in path.strip('/').split('/') if p]
    if not parts:
        return default
    seg = parts[1] if parts[0].startswith('{') and len(parts) > 1 else parts[0]
    for bucket, segs in buckets_url.items():
        if seg in segs:
            return bucket
    return default


def split(src: str, cfg: dict):
    with open(src) as f:
        lines = f.readlines()

    block_starts, blocks = detect_blocks(lines)
    if not block_starts:
        raise SystemExit(f"No top-level blocks found in {src}")

    header_text = ''.join(lines[: block_starts[0]])

    buckets_url = cfg.get('buckets_url', {})
    buckets_helper = cfg.get('buckets_helper', {})
    default_bucket = cfg.get('default_bucket', 'core')

    grouped = defaultdict(list)
    for s, e, kind, key in blocks:
        if kind == 'route':
            b = bucket_route(key, buckets_url, default_bucket)
        else:
            b = buckets_helper.get(key, default_bucket)
        grouped[b].append((s, e))

    # Output package
    base_dir, base_name = os.path.split(src)
    pkg_name = os.path.splitext(base_name)[0]
    pkg_dir = os.path.join(base_dir, pkg_name)
    os.makedirs(pkg_dir, exist_ok=True)

    sub_header = (
        f'"""{pkg_name} sub-router — split from monolithic {pkg_name}.py (T6.3).\n\n'
        f'Mounted under the parent router via {pkg_name}/__init__.py.\n"""\n'
    ) + cfg.get('header_imports', '') + '\n\nrouter = APIRouter()\n\n'

    sub_names = []
    sizes = {}
    # Discover names defined in the default bucket (helpers, classes, module-level
    # assignments) and emit explicit `from .{default} import (...)` in every other
    # sub-file. This handles cross-module references without needing star imports.
    default_names: list[str] = []
    if default_bucket in grouped:
        import ast
        body_default = ''.join(''.join(lines[s:e]) for s, e in grouped[default_bucket])
        try:
            tree = ast.parse(sub_header + body_default)
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    if node.name in ('router',):
                        continue
                    if not node.name.startswith('_') or node.name in ('_dec',):
                        default_names.append(node.name)
                elif isinstance(node, ast.Assign):
                    for t in node.targets:
                        if isinstance(t, ast.Name) and not t.id.startswith('__'):
                            if t.id in ('router', 'logger'):
                                continue
                            default_names.append(t.id)
        except SyntaxError:
            pass

    for bucket, ranges in grouped.items():
        body = ''.join(''.join(lines[s:e]) for s, e in ranges)
        out = os.path.join(pkg_dir, f'{bucket}.py')
        extra = ''
        if bucket != default_bucket and default_names:
            # Filter to names actually referenced in this body
            refs = set()
            try:
                import ast
                t2 = ast.parse(sub_header + body)
                for n in ast.walk(t2):
                    if isinstance(n, ast.Name):
                        refs.add(n.id)
            except SyntaxError:
                refs = set(default_names)
            needed = sorted(set(default_names) & refs)
            if needed:
                names_str = ', '.join(needed)
                extra = f'from .{default_bucket} import {names_str}\n\n'
        with open(out, 'w') as f:
            f.write(sub_header + extra + body)
        sizes[bucket] = (sub_header + extra + body).count('\n')
        sub_names.append(bucket)

    init_cfg = cfg['package_init']
    prefix = init_cfg['prefix']
    tags = init_cfg.get('tags', [])
    module_guard = init_cfg.get('module_guard')
    deps_extra = ''
    extra_imports = ''
    if module_guard:
        deps_extra = f', dependencies=[Depends(require_module("{module_guard}"))]'
        extra_imports = (
            'from fastapi import Depends\n'
            'from utils.permissions import require_module\n'
        )
    tags_repr = repr(tags) if tags else '[]'
    init_lines = [
        f'"""{pkg_name} router package — aggregates split sub-routers (T6.3)."""',
        'from fastapi import APIRouter',
    ]
    if extra_imports:
        init_lines.append(extra_imports.rstrip())
    init_lines.append('')
    for n_ in sub_names:
        init_lines.append(f'from .{n_} import router as _{n_}_router')
    if cfg.get('reexport_default') and default_bucket in grouped:
        init_lines.append(f'from .{default_bucket} import *  # re-export module-level names')
    init_lines.append('')
    init_lines.append(
        f'router = APIRouter(prefix="{prefix}", tags={tags_repr}{deps_extra})'
    )
    for n_ in sub_names:
        init_lines.append(f'router.include_router(_{n_}_router)')
    init_lines.append('')
    init_lines.append('__all__ = ["router"]')
    init_lines.append('')
    with open(os.path.join(pkg_dir, '__init__.py'), 'w') as f:
        f.write('\n'.join(init_lines))

    os.remove(src)
    return sizes


def main():
    if len(sys.argv) != 3:
        print("Usage: split_router.py <router.py> <config.json>")
        sys.exit(1)
    src, cfg_path = sys.argv[1], sys.argv[2]
    with open(cfg_path) as f:
        cfg = json.load(f)
    sizes = split(src, cfg)
    for k, v in sorted(sizes.items(), key=lambda kv: -kv[1]):
        print(f"  {k}.py: {v} lines")


if __name__ == '__main__':
    main()
