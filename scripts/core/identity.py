# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : identity.py
# Description : Deterministic content identity for persisted IR nodes (KF-DQ-003)
#
# Component   : Kritva Forge
# Module      : core
# Layer       : Development Infrastructure
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Stable, content-derived identity for IR nodes and source buffers.

Identity model (``IDENTITY_VERSION = 1``)
-----------------------------------------

Every persisted IR node gets::

    node_id : "n1:" + first 16 hex digits of SHA-256(identity payload)
    buffer  : repository-relative file that physically contains the
              node's first token (e.g. ``raw/rtl/original/yifive/includes/ycr_csr.svh``)

The identity payload is the ``\\x1f``-joined sequence::

    "kf-node"                 identity domain
    "v1"                      identity version
    source_file               repository-relative top-level RTL file (KF-DQ-002)
    syntax_kind               pyslang syntax class name
    start location key        see :func:`location_key`
    end location key

A location key is ``file|offset`` for ordinary file locations.  For tokens
produced by macro expansion it is
``expanded_file|expanded_offset|macro|spelling_file|spelling_offset|macro_offset``
so that the same macro expanded at two sites, and different nodes inside
one expansion, receive different identities.

Properties
~~~~~~~~~~

* Deterministic: depends only on the RTL text and the repository-relative
  paths; no ``id()``, ``hash()``, UUIDs, timestamps, PIDs, host or user
  names, absolute paths, or allocation order (pyslang ``BufferID`` numbers
  are never used).
* Portable: identical for any checkout location.
* Scope: distinct for distinct syntax nodes of one top-level source file
  (two nodes collide only if they have the same kind *and* the same exact
  start and end token positions).  The same construct parsed through the
  same file in several IPs (e.g. ``common/ctech_cells.sv``) intentionally
  receives the same identity.
* Versioned: any change to the payload must bump ``IDENTITY_VERSION``; the
  version is part of both the payload and the ``node_id`` prefix and is
  recorded in every module YAML as ``identity_version``.
"""

from __future__ import annotations

import hashlib
import os

IDENTITY_VERSION = 1
NODE_ID_DIGEST_HEX = 16
_SEP = "\x1f"


def stable_digest(*parts: object, length: int = NODE_ID_DIGEST_HEX) -> str:
    """SHA-256 hex digest of ``parts`` (stringified, unit-separator joined)."""
    payload = _SEP.join("" if p is None else str(p) for p in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:length]


def node_identity(
    source_file: str,
    syntax_kind: str,
    start_key: str,
    end_key: str,
) -> str:
    """Return the version-prefixed stable ``node_id`` for one syntax node."""
    digest = stable_digest(
        "kf-node",
        f"v{IDENTITY_VERSION}",
        source_file,
        syntax_kind,
        start_key,
        end_key,
    )
    return f"n{IDENTITY_VERSION}:{digest}"


class SourceIdentity:
    """Resolve pyslang source locations into portable identity components.

    ``source_manager`` is the pyslang ``SourceManager`` that owns the tree;
    ``to_portable`` converts an absolute file path into its
    repository-relative form (or returns it unchanged for ad-hoc runs).
    """

    def __init__(self, source_manager, to_portable):
        self._sm = source_manager
        self._to_portable = to_portable
        self._file_cache = {}

    def _file(self, loc) -> str:
        buffer = getattr(loc, "buffer", None)
        key = getattr(buffer, "id", None)
        if key in self._file_cache:
            return self._file_cache[key]
        try:
            path = self._sm.getFullPath(buffer)
            path = str(path) if path else self._sm.getFileName(loc)
        except Exception:
            path = ""
        portable = self._to_portable(os.path.normpath(path)) if path else ""
        self._file_cache[key] = portable
        return portable

    def buffer_file(self, loc) -> str:
        """Portable file that physically contains ``loc`` (macro spelling site for macros)."""
        try:
            if self._sm.isMacroLoc(loc):
                return self._file(self._sm.getFullyOriginalLoc(loc))
        except Exception:
            pass
        return self._file(loc)

    def location_key(self, loc) -> str:
        """Deterministic key for one source location (see module docstring)."""
        if loc is None:
            return ""
        try:
            if self._sm.isMacroLoc(loc):
                expanded = self._sm.getFullyExpandedLoc(loc)
                original = self._sm.getFullyOriginalLoc(loc)
                return "|".join((
                    self._file(expanded), str(expanded.offset),
                    "macro",
                    self._file(original), str(original.offset),
                    str(loc.offset),
                ))
        except Exception:
            pass
        return f"{self._file(loc)}|{getattr(loc, 'offset', -1)}"
