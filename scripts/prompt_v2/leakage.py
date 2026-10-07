# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : leakage.py
# Description : Prompt v2 answer-leakage metric v1: frozen tokenizer, overlap and run length (KF-DQ-012)
#
# Component   : Kritva Forge
# Module      : prompt_v2
# Layer       : Prompt Generation
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Answer-leakage metric v1 (KF-DQ-012 AC-287 .. AC-368; decisions D1 / D2).

Tokenizer ``sv-lex-v1``: SystemVerilog lexical tokens (sized / based
literals, unbased literals, numbers, identifiers, multi-character
operators, single characters) after removing ``/* */`` and ``//`` comments
and whitespace.  The same tokenizer is applied to the prompt and to the
completion (the module's canonical source text).

Metric ``leakage-v1`` (criteria definitions refined by M1 .. M3):

* canonical vocabulary (M1): module, port, signal, parameter / localparam,
  enum member, instance and child-module names, plus the port names of
  instantiated children (Structural Analysis connections);
* primary overlap: distinct normalized prompt 4-grams also present in the
  normalized completion / distinct normalized prompt 4-grams, where
  normalization drops HDL keywords and punctuation and maps canonical
  identifiers to ``ID``; 4-grams consisting only of ``ID`` are ignored (M2);
* longest run (M3): the longest matching block between the full lexical
  streams (identifiers included, list separators ``,`` ``;`` removed) that
  contains at least one structural token - an operator, bracket, literal,
  keyword or non-canonical identifier;
* secondary diagnostic: raw (un-normalized) distinct 4-gram overlap.

Thresholds ``thresholds-v1`` (D2): overlap <= 0.20, longest run <= 6.
Everything is locale-, order- and object-identity-independent.
"""

from __future__ import annotations

import difflib
import re

TOKENIZER_VERSION = "sv-lex-v1"
METRIC_VERSION = "leakage-v1"
THRESHOLD_VERSION = "thresholds-v1"
OVERLAP_MAX = 0.20
RUN_MAX = 6
N = 4

KEYWORDS = frozenset("""module endmodule input output inout wire reg logic integer parameter localparam assign always
always_ff always_comb always_latch begin end if else case casez casex endcase default posedge negedge or and not
for generate endgenerate genvar function endfunction task endtask initial typedef enum struct packed signed unsigned
bit byte int while repeat forever unique priority return import package endpackage interface endinterface
modport""".split())
TOKEN_RE = re.compile(r"\d+'[sS]?[bBoOdDhH][0-9a-fA-FxXzZ_?]+|'[01xXzZ]|\d+(?:\.\d+)?|[A-Za-z_$][A-Za-z0-9_$]*"
                      r"|<<<|>>>|===|!==|<=|>=|==|!=|&&|\|\||<<|>>|->|\S")
SEPARATORS = frozenset({",", ";"})
_WORD = re.compile(r"[A-Za-z0-9_$']")


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", " ", text)


def tokens(text: str) -> list:
    return TOKEN_RE.findall(strip_comments(text))


def normalized(toks: list, canon: set) -> list:
    return ["ID" if t in canon else t for t in toks if t not in KEYWORDS and _WORD.match(t)]


def ngrams(seq: list, n: int = N) -> set:
    return {tuple(seq[i:i + n]) for i in range(len(seq) - n + 1)}


def canonical_names(sem: dict, st: dict) -> set:
    """M1 canonical vocabulary of one module."""
    names = {(sem.get("module") or {}).get("name")}
    for key in ("ports", "signals", "parameters"):
        names |= {x.get("name") for x in sem.get(key, [])}
    for t in sem.get("typedefs", []):
        names |= {m.get("name") for m in t.get("members", []) or []}
    for i in sem.get("instances", []):
        names |= {i.get("name"), i.get("module")}
    for i in st.get("instances", []):
        names |= {i.get("name"), i.get("module")}
    names |= {c.get("port") for c in st.get("connections", []) if isinstance(c.get("port"), str)}
    return {n for n in names if isinstance(n, str) and n}


def measure(prompt: str, completion: str, canon: set) -> dict:
    """Leakage metrics of one prompt against its completion (deterministic)."""
    pt, ct = tokens(prompt), tokens(completion)
    pn, cn = normalized(pt, canon), normalized(ct, canon)
    pg = {g for g in ngrams(pn) if any(x != "ID" for x in g)}
    shared = pg & ngrams(cn)
    overlap = len(shared) / len(pg) if pg else 0.0
    ps = [t for t in pt if t not in SEPARATORS]
    cs = [t for t in ct if t not in SEPARATORS]
    run, run_tokens = 0, []
    sm = difflib.SequenceMatcher(None, ps, cs, autojunk=False)
    for b in sm.get_matching_blocks():
        block = ps[b.a:b.a + b.size]
        if b.size > run and any(t not in canon for t in block):
            run, run_tokens = b.size, block
    rg = ngrams(pt)
    raw = len(rg & ngrams(ct)) / len(rg) if rg else 0.0
    status = "PASS" if overlap <= OVERLAP_MAX and run <= RUN_MAX else "FAIL"
    return {
        "tokenizer_version": TOKENIZER_VERSION,
        "metric_version": METRIC_VERSION,
        "threshold_version": THRESHOLD_VERSION,
        "thresholds": {"overlap_max": OVERLAP_MAX, "longest_run_max": RUN_MAX},
        "prompt_tokens": len(pt),
        "completion_tokens": len(ct),
        "prompt_ngrams": len(pg),
        "overlapping_ngrams": len(shared),
        "overlap": round(overlap, 6),
        "longest_run": run,
        "longest_run_tokens": " ".join(run_tokens),
        "raw_overlap": round(raw, 6),
        "status": status,
    }
