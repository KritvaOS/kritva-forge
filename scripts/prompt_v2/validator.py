# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : validator.py
# Description : Prompt v2 module and corpus validation, publication gate (KF-DQ-012)
#
# Component   : Kritva Forge
# Module      : prompt_v2
# Layer       : Prompt Generation
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Prompt v2 validation (KF-DQ-012 section 25) - fail closed.

``validate_module(text, sidecar_text, inputs, variant)`` returns
``[(code, message), ...]`` for one prompt / sidecar pair against its current
inputs; ``check(data_root)`` validates the whole ``generated/prompt/v2`` tree
(inventory, every pair, corpus statistics, KF-DQ-013 consumption boundary)
and is the ``make check-prompt-v2`` gate; ``reports_check`` verifies the
presence of the four KF-DQ-012 reports.

Codes:

========================  =====================================================
``schema``                malformed sidecar / unsupported schema, generator or versions
``required``              missing sidecar field
``variant``               unknown prompt variant
``identity``              malformed or non-derivable Prompt identity
``mismatch``              prompt bytes disagree with the sidecar (sha256 / size)
``provenance``            missing or wrong upstream / source reference
``stale``                 upstream changed since generation, or regeneration differs
``input``                 upstream input missing or unsupported (generation refused)
``fabricated``            a prompt fact that the upstream documents do not support
``hdl_syntax``            HDL statement / expression syntax in the prompt
``parser_metadata``       parser-only fields in the prompt
``absolute_path``         absolute or machine-local path
``ordering``              sections out of the frozen order
``vocabulary``            marker outside the uncertainty vocabulary
``truncation``            truncation notices and sidecar metadata disagree
``size``                  prompt exceeds the 32 KiB budget
``leakage``               answer-leakage metric failed or disagrees with the sidecar
``inventory``             orphan / unmanaged / missing Prompt v2 artifact (corpus)
``consumption``           a dataset record consumes Prompt v2 before KF-DQ-013 (corpus)
``report``                a required KF-DQ-012 report is missing or invalid
========================  =====================================================
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

from scripts.prompt_v2 import leakage as L
from scripts.prompt_v2 import model as P
from scripts.prompt_v2 import render as R

REQUIRED = ("schema", "generator", "versions", "module", "variant", "inputs", "source", "prompt", "abstraction",
            "uncertainty", "fsm", "leakage", "identity")
_FSM_HEAD = re.compile(r"^FSM (\d+): state register (.+?) \(.*?\); status (\w+);")
_BRACKET = re.compile(r"\[[^\]\n]*\]")
_UNKNOWN_KINDS = None


def _unknown_kinds():
    global _UNKNOWN_KINDS
    if _UNKNOWN_KINDS is None:
        from scripts.fsm import model as FM
        _UNKNOWN_KINDS = {k.replace("_", " ") for k in FM.UNKNOWN_KINDS}
    return _UNKNOWN_KINDS


def _sections(text: str) -> dict:
    out, cur = {}, None
    for line in text.split("\n"):
        if line.startswith("## "):
            cur = line[3:]
            out[cur] = []
        elif cur is not None and line:
            out[cur].append(line)
    return out


def text_problems(text: str) -> list:
    """Checks that need only the prompt text (abstraction, vocabulary, order, size)."""
    p = []
    if not text.startswith(P.PREAMBLE + "\n"):
        p.append(("ordering", "prompt does not start with the frozen behavior_aware preamble"))
    m = P.HDL_SYNTAX_RE.search(text)
    if m:
        p.append(("hdl_syntax", f"HDL syntax {m.group(0)!r} in the prompt"))
    m = P.HDL_SELECT_RE.search(text)
    if m:
        p.append(("hdl_syntax", f"HDL index / select syntax near {text[max(0, m.start() - 20):m.end() + 10]!r}"))
    m = P.PARSER_NOISE_RE.search(text)
    if m:
        p.append(("parser_metadata", f"parser metadata {m.group(0)!r} in the prompt"))
    m = P.ABS_PATH_RE.search(text)
    if m:
        p.append(("absolute_path", f"absolute path {m.group(0).strip()!r} in the prompt"))
    secs = [line[3:] for line in text.split("\n") if line.startswith("## ")]
    if any(s not in P.SECTIONS for s in secs):
        p.append(("ordering", f"unknown section(s) {[s for s in secs if s not in P.SECTIONS]}"))
    elif secs != [s for s in P.SECTIONS if s in secs] or len(set(secs)) != len(secs):
        p.append(("ordering", f"sections out of the frozen order: {secs}"))
    if len(text.encode("utf-8")) > P.BUDGET_BYTES:
        p.append(("size", f"prompt is {len(text.encode('utf-8'))} bytes (budget {P.BUDGET_BYTES})"))
    for b in _BRACKET.findall(text):
        if b not in P.BRACKET_MARKERS and not P.TRUNCATION_RE.match(b):
            p.append(("vocabulary", f"marker {b!r} is not in the uncertainty vocabulary"))
    for line in text.split("\n"):
        h = _FSM_HEAD.match(line)
        if h and h.group(3) not in P.FSM_STATUS:
            p.append(("vocabulary", f"FSM status {h.group(3)!r} is not in the vocabulary"))
        if line.startswith("Uncertain: "):
            bad = [k for k in line[len("Uncertain: "):].split(", ") if k not in _unknown_kinds()]
            if bad:
                p.append(("vocabulary", f"uncertainty kind(s) {bad} not in the FSM unknown vocabulary"))
    return p


def _fact_problems(text: str, expected: str) -> list:
    """Prompt facts the upstream documents do not support (AC-669, AC-768 .. AC-775)."""
    p = []
    have, want = _sections(text), _sections(expected)
    heads = {}
    for line in want.get("State machines", []):
        h = _FSM_HEAD.match(line)
        if h:
            heads[h.group(1)] = (h.group(2), h.group(3))
    for line in have.get("State machines", []):
        h = _FSM_HEAD.match(line)
        if h and h.group(1) in heads and heads[h.group(1)][1] != h.group(3):
            p.append(("fabricated", f"FSM {h.group(1)} ({h.group(2)}) rendered as {h.group(3)}, upstream status is "
                                    f"{heads[h.group(1)][1]}"))
    for sec, lines in have.items():
        known = set(want.get(sec, []))
        for line in lines:
            if line not in known and not P.TRUNCATION_RE.match(line) and not _FSM_HEAD.match(line):
                p.append(("fabricated", f"{sec}: {line[:120]!r} is not supported by the upstream documents"))
    return p


def validate_module(text, sidecar_text, inputs=None, variant=P.DEFAULT_VARIANT) -> list:
    p = []
    if not isinstance(text, str):
        return [("required", "prompt text missing")]
    try:
        sc = json.loads(sidecar_text) if isinstance(sidecar_text, str) else sidecar_text
    except ValueError as exc:
        return [("schema", f"sidecar is not valid JSON ({exc})")]
    if not isinstance(sc, dict):
        return [("schema", "sidecar is not a JSON object")]
    missing = [k for k in REQUIRED if k not in sc]
    if missing:
        return [("required", f"sidecar lacks {missing}")]
    if sc["schema"] != {"name": P.SCHEMA_NAME, "version": P.SCHEMA_VERSION}:
        p.append(("schema", f"unsupported Prompt schema {sc['schema']!r}"))
    if sc["generator"] != {"name": P.GENERATOR, "version": P.GENERATOR_VERSION}:
        p.append(("schema", f"unsupported Prompt generator {sc['generator']!r}"))
    if sc["versions"] != R.versions():
        diff = sorted(k for k in set(sc["versions"]) | set(R.versions())
                      if (sc["versions"] or {}).get(k) != R.versions().get(k))
        code = "leakage" if any(k in ("tokenizer", "leakage_metric", "leakage_thresholds") for k in diff) else "schema"
        p.append((code, f"unsupported versions {diff}"))
    if sc["variant"] not in P.VARIANTS or sc["variant"] != variant:
        p.append(("variant", f"unsupported prompt variant {sc['variant']!r}"))
    ident = sc.get("identity")
    if not isinstance(ident, str) or not P.ID_RE.fullmatch(ident) or ident != P.identity(sc):
        p.append(("identity", f"Prompt identity {ident!r} is not derived from the sidecar"))
    pr = sc.get("prompt") or {}
    if pr.get("sha256") != P.sha256_text(text) or pr.get("bytes") != len(text.encode("utf-8")):
        p.append(("mismatch", "prompt text disagrees with the sidecar (sha256 / size)"))
    if P.ABS_PATH_RE.search(P.dumps(sc)):
        p.append(("absolute_path", "absolute path in the sidecar"))
    p += text_problems(text)
    notices = [m for m in (P.TRUNCATION_RE.match(line) for line in text.split("\n")) if m]
    noted = [{"section": m.group(1), "emitted": int(m.group(2)), "total": int(m.group(3))} for m in notices]
    if sorted(noted, key=lambda x: x["section"]) != sorted(pr.get("truncated_sections") or [], key=lambda x: x["section"]) \
            or bool(noted) != bool(pr.get("truncated")):
        p.append(("truncation", "truncation notices and sidecar truncation metadata disagree"))
    lk = sc.get("leakage") or {}
    if (lk.get("tokenizer_version"), lk.get("metric_version"), lk.get("threshold_version")) != \
            (L.TOKENIZER_VERSION, L.METRIC_VERSION, L.THRESHOLD_VERSION):
        p.append(("leakage", "unsupported tokenizer / leakage metric / threshold version"))
    if lk.get("status") != "PASS" or not (isinstance(lk.get("overlap"), (int, float)) and lk["overlap"] <= L.OVERLAP_MAX) \
            or not (isinstance(lk.get("longest_run"), int) and lk["longest_run"] <= L.RUN_MAX):
        p.append(("leakage", f"answer leakage: overlap {lk.get('overlap')!r}, longest run {lk.get('longest_run')!r}"))
    if inputs is None:
        return p
    ip, module = inputs["ip"], inputs["module"]
    if (sc.get("module") or {}).get("ip") != ip or (sc.get("module") or {}).get("name") != module \
            or (sc.get("module") or {}).get("module_id") != \
            ((inputs["docs"]["semantic_ir"].get("module") or {}).get("module_id")):
        p.append(("provenance", "sidecar module identity disagrees with the inputs"))
    if pr.get("path") != P.prompt_rel(ip, module, sc["variant"] if sc["variant"] in P.VARIANTS else variant):
        p.append(("provenance", f"prompt path {pr.get('path')!r} is not the canonical layout path"))
    ins = sc.get("inputs") or {}
    for layer in P.UPSTREAM:
        ref = ins.get(layer)
        if not isinstance(ref, dict) or not ref.get("path") or not ref.get("sha256"):
            p.append(("provenance", f"missing {layer} provenance"))
            continue
        if ref.get("path") != inputs["rels"][layer]:
            p.append(("provenance", f"{layer} path {ref.get('path')!r} is not {inputs['rels'][layer]}"))
        if ref.get("sha256") != inputs["shas"][layer]:
            p.append(("stale", f"derived from an older {layer} revision"))
        if (ref.get("schema_version"), ref.get("identity_version")) != P.UPSTREAM[layer][1:3]:
            p.append(("schema", f"{layer} schema / identity version {ref.get('schema_version')!r} / "
                                f"{ref.get('identity_version')!r} unsupported"))
    if sc.get("source") != inputs["source"]:
        p.append(("provenance", "source reference disagrees with Semantic IR"))
    try:
        exp_text, exp_sc = R.render(inputs, sc["variant"] if sc["variant"] in P.VARIANTS else variant)
    except R.PromptError as exc:
        return p + [("input", str(exc))]
    if text != exp_text:
        p += _fact_problems(text, exp_text) or [("stale", "prompt differs from a regeneration from the current inputs")]
    if lk != exp_sc["leakage"]:
        p.append(("leakage", "sidecar leakage metrics differ from a re-measurement"))
    if P.dumps(sc) != P.dumps(exp_sc) and not any(c in ("stale", "fabricated", "leakage") for c, _ in p):
        p.append(("stale", "sidecar differs from a regeneration from the current inputs"))
    return p


# =============================================================================
# corpus
# =============================================================================

def corpus_sha256(data_root) -> str:
    root = Path(os.path.abspath(data_root))
    base = root / P.OUTPUT_DIR
    h = hashlib.sha256()
    for path in sorted(base.rglob("*")) if base.is_dir() else []:
        if path.is_file():
            h.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0" + path.read_bytes() + b"\0")
    return h.hexdigest()


def consumption(data_root) -> list:
    """KF-DQ-013 boundary (AC-030, AC-648, AC-785): no dataset record may consume Prompt v2 yet."""
    from scripts.core.provenance import iter_dataset_records
    root = Path(os.path.abspath(data_root))
    problems = []
    for split, _, rec in iter_dataset_records(root):
        variant = str(rec.get("prompt_variant") or "")
        prov = rec.get("provenance") or {}
        if "prompt_v2" in prov or any(v in variant for v in P.VARIANTS) or P.OUTPUT_DIR in json.dumps(prov):
            problems.append(("consumption", f"record {prov.get('record_id')} ({split}) consumes Prompt v2 before "
                                            "KF-DQ-013"))
    return problems


def _quantiles(values: list) -> dict:
    v = sorted(values)
    if not v:
        return {}
    return {f"p{q}": v[min(len(v) - 1, int(round(q / 100 * (len(v) - 1))))] for q in (0, 50, 90, 95, 99, 100)}


def check(data_root, with_classification: bool = False) -> dict:
    from scripts.core.paths import find_absolute_paths

    root = Path(os.path.abspath(data_root))
    base = root / P.OUTPUT_DIR
    canonical = set(R.canonical_modules(root))
    problems, present = [], {}
    pat = re.compile(r"^([^/]+)/([^/]+)\.([A-Za-z0-9_]+)\.(txt|json)$")
    for path in sorted(base.rglob("*")) if base.is_dir() else []:
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        m = pat.match(path.relative_to(base).as_posix())
        if not m:
            problems.append(("inventory", f"{rel}: unmanaged (not <ip>/<module>.<variant>.txt|json)"))
            continue
        ip, module, variant, ext = m.groups()
        if variant not in P.VARIANTS:
            problems.append(("variant", f"{rel}: unsupported prompt variant {variant!r}"))
            continue
        if (ip, module) not in canonical:
            problems.append(("inventory", f"{rel}: orphan (no canonical module {ip}/{module})"))
            continue
        present.setdefault((ip, module, variant), set()).add(ext)
    sizes, overlaps, runs, truncated, fallbacks = [], [], [], 0, 0
    unc, fsm, valid = Counter(), Counter(), 0
    for ip, module in sorted(canonical):
        for variant in P.VARIANTS:
            exts = present.get((ip, module, variant), set())
            prel, srel = P.prompt_rel(ip, module, variant), P.sidecar_rel(ip, module, variant)
            if "txt" not in exts and "json" not in exts:
                problems.append(("inventory", f"missing Prompt v2 for {ip}/{module} ({variant})"))
                continue
            if "txt" not in exts:
                problems.append(("inventory", f"{srel}: orphan sidecar (prompt missing)"))
                continue
            if "json" not in exts:
                problems.append(("inventory", f"{prel}: sidecar missing"))
                continue
            text = (root / prel).read_text(encoding="utf-8")
            stext = (root / srel).read_text(encoding="utf-8")
            if find_absolute_paths(text) or find_absolute_paths(stext):
                problems.append(("absolute_path", f"{prel}: absolute path"))
            try:
                inputs = R.load_inputs(root, ip, module)
            except R.PromptError as exc:
                problems.append(("input", f"{prel}: {exc}"))
                continue
            found = validate_module(text, stext, inputs, variant)
            for code, msg in found:
                problems.append((code, f"{prel}: {msg}"))
            try:
                sc = json.loads(stext)
            except ValueError:
                continue
            if json.dumps(sc, sort_keys=True, indent=2, ensure_ascii=False) + "\n" != stext:
                problems.append(("ordering", f"{srel}: not in canonical serialisation"))
            if not found:
                valid += 1
            pr, lk = sc.get("prompt") or {}, sc.get("leakage") or {}
            sizes.append(pr.get("bytes", 0))
            truncated += 1 if pr.get("truncated") else 0
            overlaps.append(lk.get("overlap", 0))
            runs.append(lk.get("longest_run", 0))
            fallbacks += (sc.get("abstraction") or {}).get("guard_fallbacks", 0)
            for k, v in ((sc.get("uncertainty") or {}).get("by_category") or {}).items():
                unc[k] += v
            f = sc.get("fsm") or {}
            fsm["prompts_with_fsms"] += 1 if f.get("fsms") else 0
            for k in ("fsms", "confirmed", "candidate", "ambiguous", "unsupported", "states", "transitions",
                      "transitions_rendered", "actions_rendered", "unknowns", "couplings"):
                fsm[k] += f.get(k, 0)
            fsm["section_truncated"] += 1 if f.get("section_truncated") else 0
            for q, n in (f.get("quality") or {}).items():
                fsm[f"quality_{q}"] += n
    problems += consumption(root)
    classification = {"status": "SKIPPED"}
    if with_classification:
        from scripts.prompt_v2 import classify as PC
        try:
            rep = PC.build(root)
            bad = PC.validate(rep)
            classification = {"status": "FAIL" if bad else "PASS", "classifier_version": rep["classifier_version"],
                              **rep["counts"], "unresolved_near_duplicates": rep["unresolved_near_duplicates"],
                              "kf_dq_013_entry": rep["kf_dq_013_entry"]}
            problems += [("report", f"classification: {b}") for b in bad]
        except PC.ClassificationError as exc:
            classification = {"status": "FAIL", "reason": str(exc)}
            problems.append(("report", f"classification refused: {exc}"))
    codes = Counter(c for c, _ in problems)
    n = len(canonical) * len(P.VARIANTS)
    return {
        "schema": {"name": P.SCHEMA_NAME + "-report", "version": 1},
        "generator": P.GENERATOR,
        "versions": R.versions(),
        "canonical_modules": len(canonical),
        "prompts": sum(1 for v in present.values() if "txt" in v),
        "sidecars": sum(1 for v in present.values() if "json" in v),
        "corpus_sha256": corpus_sha256(root),
        "sizes": {"budget_bytes": P.BUDGET_BYTES, **_quantiles(sizes), "truncated": truncated,
                  "truncation_rate": round(truncated / n, 6) if n else 0.0},
        "leakage": {"tokenizer_version": L.TOKENIZER_VERSION, "metric_version": L.METRIC_VERSION,
                    "threshold_version": L.THRESHOLD_VERSION,
                    "thresholds": {"overlap_max": L.OVERLAP_MAX, "longest_run_max": L.RUN_MAX},
                    "records": len(overlaps), "failures": sum(1 for c, _ in problems if c == "leakage"),
                    "overlap": _quantiles(overlaps), "longest_run": _quantiles(runs)},
        "abstraction": {"guard_fallbacks": fallbacks},
        "uncertainty": dict(sorted(unc.items())),
        "fsm": dict(sorted(fsm.items())),
        "provenance": {"prompts": n, "valid": valid, "coverage": round(valid / n, 6) if n else 0.0},
        "classification": classification,
        "problem_counts": dict(sorted(codes.items())),
        "problems": [f"[{c}] {m}" for c, m in problems[:200]],
        "status": "FAIL" if problems else "PASS",
    }


def reports_check(data_root) -> list:
    """The KF-DQ-012 reports must exist and be well-formed (AC-795 .. AC-798)."""
    from scripts.core import compat as C
    from scripts.core import stale_artifacts as S
    from scripts.prompt_v2 import classify as PC

    root = Path(os.path.abspath(data_root))
    problems = []
    for rel, what in ((P.REPORT_PATH, "corpus"), (C.REPORT_PATH, "compatibility"), (S.REPORT_PATH, "stale"),
                      (P.CLASSIFICATION_REPORT_PATH, "leakage classification")):
        path = root / rel
        if not path.is_file():
            problems.append(("report", f"{what} report {rel} missing"))
            continue
        try:
            rep = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            problems.append(("report", f"{what} report {rel} is not valid JSON"))
            continue
        if rel == P.CLASSIFICATION_REPORT_PATH:
            problems += [("report", f"classification: {b}") for b in PC.validate(rep)]
        elif rep.get("status") != "PASS":
            problems.append(("report", f"{what} report {rel} status {rep.get('status')!r}"))
    return problems


def write_report(data_root, report: dict) -> Path:
    path = Path(os.path.abspath(data_root)) / P.REPORT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def format_report(report: dict) -> str:
    s, lk = report["sizes"], report["leakage"]
    lines = [f"Prompt v2 check: {report['status']} (schema {P.SCHEMA_NAME} v{P.SCHEMA_VERSION})",
             f"  prompts / sidecars / modules : {report['prompts']} / {report['sidecars']} / {report['canonical_modules']}",
             f"  size p50 / p99 / max         : {s.get('p50')} / {s.get('p99')} / {s.get('p100')} bytes "
             f"(budget {s['budget_bytes']}; truncated {s['truncated']})",
             f"  leakage overlap max / run max: {lk['overlap'].get('p100')} / {lk['longest_run'].get('p100')} "
             f"(thresholds {lk['thresholds']['overlap_max']} / {lk['thresholds']['longest_run_max']}; failures "
             f"{lk['failures']})",
             f"  provenance coverage          : {report['provenance']['valid']}/{report['provenance']['prompts']}",
             f"  classification               : {report['classification'].get('status')}"
             + (f" (near_duplicate {report['classification'].get('near_duplicate')}, structural_similarity "
                f"{report['classification'].get('structural_similarity')}, informational "
                f"{report['classification'].get('informational')})" if 'groups' in report['classification'] else "")]
    lines += [f"  [FAIL] {p}" for p in report["problems"][:30]]
    if len(report["problems"]) > 30:
        lines.append(f"  ... {len(report['problems']) - 30} more")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="KF-DQ-012 Prompt v2 validator")
    parser.add_argument("--data-root", default=os.environ.get("KRITVA_FORGE_DATA_ROOT"))
    parser.add_argument("--check", action="store_true", help="validate the corpus (default)")
    parser.add_argument("--with-classification", action="store_true", help="include the cross-split classification")
    parser.add_argument("--reports", action="store_true", help="also require the four KF-DQ-012 reports")
    parser.add_argument("--json", help="also write the report JSON here")
    args = parser.parse_args(argv)
    if not args.data_root:
        from scripts.core.paths import default_data_root
        args.data_root = str(default_data_root())
    report = check(args.data_root, with_classification=args.with_classification)
    if args.reports:
        extra = reports_check(args.data_root)
        report["problems"] += [f"[{c}] {m}" for c, m in extra]
        if extra:
            report["status"] = "FAIL"
    print(format_report(report))
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
