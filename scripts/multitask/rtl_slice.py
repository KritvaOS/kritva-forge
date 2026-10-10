# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : rtl_slice.py
# Description : rtl-slice-v1 - lexical module-declaration slice of a canonical source file (KF-DQ-013)
#
# Component   : Kritva Forge
# Module      : multitask
# Layer       : Dataset
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""``rtl-slice-v1`` (KF-DQ-013 AC-020 .. AC-022).

The canonical source text of exactly one module declaration: from the
``module`` / ``macromodule`` keyword followed by the module name to the next
``endmodule`` keyword.  Comments and string literals are masked (replaced by
spaces of equal length) only to locate the keywords; the emitted slice keeps
their original content.  The only normalization is CRLF / CR -> LF.  This is
syntactic slicing, not semantic analysis - no fact is derived from the RTL.
Zero or several matching declarations fail; there is no whole-file fallback.
"""

from __future__ import annotations

import re

VERSION = "rtl-slice-v1"

_MASK = re.compile(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\\n])*"', re.S)


class SliceError(RuntimeError):
    """The module declaration cannot be located uniquely (fail closed)."""


def normalize(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def mask(text: str) -> str:
    """Comments and strings replaced by spaces (newlines kept), offsets unchanged."""
    return _MASK.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)


def module_slice(source_text: str, module: str) -> str:
    text = normalize(source_text)
    masked = mask(text)
    starts = [m.start() for m in re.finditer(r"\b(?:module|macromodule)\s+" + re.escape(module) + r"(?![A-Za-z0-9_$])",
                                             masked)]
    if len(starts) != 1:
        raise SliceError(f"{len(starts)} declarations of module {module!r} (exactly one required)")
    end = re.search(r"\bendmodule\b", masked[starts[0]:])
    if not end:
        raise SliceError(f"module {module!r}: no endmodule")
    return text[starts[0]: starts[0] + end.end()]
