"""Cheap trees for the factory's candidate checks (no LLM, standard library only).

A full copy of the repository per attempt cost seconds of laptop disk for a check that the cloud runs from the base commit
anyway. A *sparse* tree holds only the files a candidate changed plus a marker naming its base: the cloud route reads
"base + these files" (factory_cloud_gate), the local route calls ``materialize`` once, right before pytest, and gets exactly
the tree a full copy gave. The base is never written.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

MARKER = '.factory_sparse'
COPY_IGNORE = shutil.ignore_patterns('.git', '__pycache__', '.pytest_cache', '.env*', 'SECRETS_LOCAL', '*.pem', '*.key')


def sparse_tree(base, into, files) -> Path:
    """``into/tree`` with only ``files`` ({relative posix name: bytes | source Path}) and a marker naming ``base``."""
    tree = Path(into) / 'tree'
    tree.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        dest = tree.joinpath(*name.split('/'))
        dest.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, (bytes, bytearray)):
            dest.write_bytes(bytes(data))
        else:
            shutil.copyfile(data, dest)
    (tree / MARKER).write_text(json.dumps({'base': str(Path(base))}), encoding='utf-8')
    return tree


def base_of(tree):
    """The base a sparse tree stands on, or None for a full tree."""
    try:
        return Path(json.loads((Path(tree) / MARKER).read_text(encoding='utf-8'))['base'])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def is_sparse(tree) -> bool:
    return base_of(tree) is not None


def materialize(tree) -> Path:
    """Fill a sparse tree in from its base (a real copy; the files already there win) and drop the marker. A full tree is
    left as it is. A base that is gone raises OSError: the caller's pass is released, never judged on half a tree."""
    tree = Path(tree)
    base = base_of(tree)
    if base is None:
        return tree

    def keep_existing(src, dst):
        if not Path(dst).exists():
            return shutil.copy2(src, dst)
        return dst
    if not base.is_dir():
        raise OSError('base tree is gone')
    shutil.copytree(base, tree, ignore=COPY_IGNORE, dirs_exist_ok=True, copy_function=keep_existing)
    (tree / MARKER).unlink()
    return tree


def read_bytes(tree, rel):
    """The bytes of ``rel`` in a full or a sparse tree (a sparse one falls back to its base); None when there is none."""
    for root in (Path(tree), base_of(tree)):
        if root is None:
            continue
        try:
            return (root.joinpath(*rel.split('/'))).read_bytes()
        except OSError:
            continue
    return None
