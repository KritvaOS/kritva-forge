#!/usr/bin/env python3
# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : run_pipeline.py
# Description : Run Pipeline implementation
#
# Component   : Kritva Forge
# Module      : pipeline
# Layer       : Pipeline
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
#--------------------------------------------------------------
#     Feature :
#          ✓ files.f flow
#          ✓ common library folder
#          ✓ hierarchy generation
#          ✓ module YAML generation
#          ✓ prompt generation
#          ✓ RTL copy
#          ✓ centralized datasets/
#          ✓ prompt -> RTL
#          ✓ yaml -> RTL
#          ✓ hierarchy -> RTL
#          ✓ RTL -> YAML
#          ✓ RTL -> hierarchy
#          ✓ dataset statistics
#          ✓ error handling
#     Purpose:  Automation layer.
#                  RTL Source
#                        │
#                        ▼
#                    rtl_parser.py
#                        │
#                        ▼
#                    Module Database
#                        │
#                        ▼
#                    yaml_generator.py
#                        │
#                        ├── hierarchy.yaml
#                        ├── modules/*.yaml
#                        ├── prompts/*.txt
#                        └── rtl/*.v
#                        │
#                        ▼
#                    dataset_generator.py
#                        │
#                        ├── dataset_prompt.jsonl
#                        ├── dataset_yaml.jsonl
#                        ├── dataset_hierarchy.jsonl
#                        └── dataset_mixed.jsonl
#                        │
#                        ▼
#                    LLM Fine-tuning
#   Change History:
#       <Rev0.1> <7June 2026>
#           ✅ Skip common/
#           ✅ Support filelist (files.f) flow
#           ✅ Better logging
#           ✅ Dataset statistics
#           ✅ Dataset folder creation
#           ✅ Per-IP summary
#           ✅ Graceful error handling
#---------------------------------------------------------
#  Expected input layout (private data repository, KF-DQ-001):
#     <data-root>/raw/rtl/original/
#      ├── common/                 shared library RTL (not an IP)
#      ├── uart/
#      │   ├── files.f
#      │   └── *.v / *.sv
#      └── ...
#
#  Canonical outputs:
#     <data-root>/normalized/ir/<ip>/hierarchy.yaml
#     <data-root>/normalized/ir/<ip>/summary.yaml
#     <data-root>/normalized/ir/<ip>/modules/<module>.yaml
#     <data-root>/generated/prompts/<ip>/
#     <data-root>/analysis/reports/
#     <data-root>/datasets/pipeline/
#
#  Usage (preferred):
#     PYTHONPATH=. python -m scripts.pipeline.run_pipeline \
#         --data-root ../kritva-forge-data
#  or explicit roots (see `make pipeline`):
#     PYTHONPATH=. python -m scripts.pipeline.run_pipeline \
#         --rtl-root ... --normalized-root ... --prompt-root ... \
#         --reports-root ... --datasets-root ...
#
#  Prompts, reports and datasets are never written inside normalized_root.
#--------------------------------------------------------------

import json
import os
import sys
import traceback

# Allow ``python scripts/pipeline/run_pipeline.py`` (script mode) in addition
# to ``python -m scripts.pipeline.run_pipeline``.
if __package__ in (None, ""):
    sys.path.insert(
        0,
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    )

from scripts.parser.rtl_parser_slang import parse_ip
from scripts.dataset.yaml_generator import write_ip_outputs
from scripts.dataset.dataset_generator import generate_datasets
from scripts.parser.statistics import print_summary
from scripts.pipeline.run_semantic import run_semantic

import logging
from pathlib import Path

from scripts.core.paths import (
    ForgeDataPaths,
    find_noncanonical_module_yamls,
    infer_data_root,
    scan_absolute_paths,
)

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s",
)

GENERATE_DATASETS = True

ENABLE_SEMANTIC = True



def discover_ips(rtl_root):
    """Discover IP compilation units below ``rtl_root``.

    A directory is an IP when it contains ``files.f`` or at least one
    Verilog/SystemVerilog source file.  The root itself may also be one IP.
    """

    rtl_root = os.path.abspath(rtl_root)
    if not os.path.isdir(rtl_root):
        raise FileNotFoundError(f"RTL root does not exist: {rtl_root}")

    def has_rtl(path):
        if os.path.isfile(os.path.join(path, "files.f")):
            return True
        for name in os.listdir(path):
            if name.lower().endswith((".v", ".sv")):
                return True
        return False

    if has_rtl(rtl_root):
        return [rtl_root]

    ips = []
    for name in sorted(os.listdir(rtl_root)):
        if name.startswith(".") or name == "common":
            continue
        ip_dir = os.path.join(rtl_root, name)
        if os.path.isdir(ip_dir) and has_rtl(ip_dir):
            ips.append(ip_dir)

    return ips


def process_ip(ip_dir, normalized_root, prompt_root, data_root=None):
    """Parse one IP and generate normalized IR plus prompts."""

    ip_name = os.path.basename(os.path.normpath(ip_dir))

    print(f"\n{'=' * 60}")
    print(f"[INFO] Processing IP: {ip_name}")
    print(f"{'=' * 60}")

    modules, top = parse_ip(ip_dir, data_root=data_root)

    semantic_ctx = run_semantic(modules) if ENABLE_SEMANTIC else None

    write_ip_outputs(
        ip_name,
        modules,
        top,
        normalized_root,
        semantic_ctx=semantic_ctx,
        prompt_root=prompt_root,
    )

    return {
        "ip": ip_name,
        "top": top,
        "modules": len(modules),
        "semantic": semantic_ctx,
    }


def save_pipeline_stats(results, reports_root):
    """Write pipeline summary under the private data repository."""

    os.makedirs(reports_root, exist_ok=True)

    stats = {
        "pipeline_version": "v2",
        "ips": len(results),
        "modules": sum(r["modules"] for r in results),
        "top_modules": {r["ip"]: r["top"] for r in results},
    }

    path = os.path.join(reports_root, "pipeline_stats.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)

    return path


def print_pipeline_summary(results):
    print("\n" + "=" * 60)
    print("PIPELINE SUMMARY")
    print("=" * 60)
    print(f"IPs processed : {len(results)}")
    print(f"Modules       : {sum(r['modules'] for r in results)}")
    print("\nTop Modules:")
    for result in results:
        print(f"  {result['ip']:20s} -> {result['top']}")


def _is_within(path, root):
    path = os.path.abspath(path)
    root = os.path.abspath(root)
    return os.path.commonpath([path, root]) == root


def default_output_roots(normalized_root):
    """Default prompt/report/dataset roots for a given ``normalized_root``.

    When ``normalized_root`` is ``<data-root>/normalized/ir`` the canonical
    ``ForgeDataPaths`` locations are used.  Otherwise outputs go to siblings of
    ``normalized_root`` (never inside it).
    """
    normalized_root = Path(os.path.abspath(normalized_root))

    if (normalized_root.name == "ir"
            and normalized_root.parent.name == "normalized"):
        data = ForgeDataPaths.from_root(normalized_root.parent.parent)
        return {
            "prompts": str(data.prompts),
            "reports": str(data.reports),
            "datasets": str(data.pipeline_datasets),
        }

    parent = normalized_root.parent
    return {
        "prompts": str(parent / "prompts"),
        "reports": str(parent / "reports"),
        "datasets": str(parent / "datasets"),
    }


def check_canonical_layout(normalized_root):
    """Fail if any non-canonical module YAML exists under ``normalized_root``."""
    stale = find_noncanonical_module_yamls(normalized_root)
    if stale:
        sample = "\n  ".join(str(p) for p in stale[:10])
        raise RuntimeError(
            f"{len(stale)} non-canonical module YAML(s) found directly under "
            f"<ip>/ in {normalized_root}; only <ip>/modules/<module>.yaml is "
            f"canonical (KF-DQ-001). First entries:\n  {sample}"
        )


def check_portable_provenance(roots):
    """Fail if any artifact under ``roots`` contains an absolute host path (KF-DQ-002)."""
    findings = scan_absolute_paths(roots)
    if findings:
        sample = "\n  ".join(
            f"{path}:{line_no}: {line.strip()[:120]}"
            for path, line_no, line in findings[:10]
        )
        raise RuntimeError(
            f"{len(findings)} absolute host path(s) found in persisted "
            f"artifacts; provenance must be repository-relative (KF-DQ-002). "
            f"First entries:\n  {sample}"
        )


def run_pipeline(
        rtl_root,
        normalized_root,
        datasets_root=None,
        reports_root=None,
        prompt_root=None,
        curated_root=None,
        data_root=None):
    """Run the complete Forge RTL analysis pipeline.

    ``normalized_root`` contains only canonical IR:
    ``<ip>/{hierarchy.yaml,summary.yaml,modules/<module>.yaml}``.
    Prompts, reports, and datasets go to their dedicated data-repository
    locations (see ``default_output_roots``) and never inside
    ``normalized_root``.

    ``data_root`` is the data-repository root used for portable provenance
    (``raw/rtl/original/...``); it is inferred from ``rtl_root`` if omitted.
    """

    normalized_root = os.path.abspath(normalized_root)
    defaults = default_output_roots(normalized_root)
    if prompt_root is None:
        prompt_root = defaults["prompts"]
    if datasets_root is None:
        datasets_root = defaults["datasets"]
    if reports_root is None:
        reports_root = defaults["reports"]

    for name, path in (
            ("prompt_root", prompt_root),
            ("datasets_root", datasets_root),
            ("reports_root", reports_root)):
        if _is_within(path, normalized_root):
            raise ValueError(
                f"{name} must not be inside normalized_root "
                f"({path} is under {normalized_root})"
            )

    for path in (normalized_root, prompt_root, datasets_root, reports_root):
        os.makedirs(path, exist_ok=True)

    if data_root is None:
        data_root = infer_data_root(rtl_root)
    if data_root is None:
        raise ValueError(
            f"cannot determine the data-repository root for {rtl_root}; "
            "pass data_root/--data-root so provenance can be recorded "
            "repository-relative (KF-DQ-002)"
        )
    data_root = os.path.abspath(data_root)
    # KF-DQ-004: split manifest lives in <data-root>/splits.
    splits_root = str(ForgeDataPaths.from_root(data_root).splits)
    print("[INFO] Provenance     : repository-relative (raw/rtl/...)")

    ips = discover_ips(rtl_root)
    print(f"[INFO] Found {len(ips)} IPs")

    if not ips:
        raise RuntimeError(f"No RTL IPs found under {os.path.abspath(rtl_root)}")

    results = []
    for ip_dir in ips:
        try:
            results.append(
                process_ip(
                    ip_dir,
                    normalized_root,
                    prompt_root,
                    data_root=data_root,
                )
            )
        except Exception as exc:
            print("\n" + "=" * 80)
            print("[PIPELINE ERROR]")
            print("IP Directory :", ip_dir)
            print("Exception    :", type(exc).__name__)
            print("Message      :", exc)
            print("-" * 80)
            traceback.print_exc()
            print("=" * 80)
            raise

    check_canonical_layout(normalized_root)

    stats_path = save_pipeline_stats(results, reports_root)
    print(f"[INFO] Pipeline statistics: {stats_path}")

    if GENERATE_DATASETS:
        print("\n" + "=" * 60)
        print("[INFO] Generating datasets")
        print("=" * 60)

        generate_datasets(
            normalized_root,
            datasets_root,
            prompt_root=prompt_root,
            curated_root=curated_root,
            splits_root=splits_root,
            reports_root=reports_root,
        )

    check_portable_provenance(
        [normalized_root, prompt_root, reports_root, datasets_root, splits_root]
    )
    print("[INFO] Portable provenance OK (no absolute host paths)")

    print_pipeline_summary(results)
    print_summary()
    return results


def parse_args():
    import argparse

    parser = argparse.ArgumentParser(
        description="Run the Kritva Forge RTL analysis pipeline."
    )
    parser.add_argument(
        "legacy_rtl_root",
        nargs="?",
        help="RTL/IP root. Legacy positional interface.",
    )
    
    parser.add_argument(
        "legacy_out_root",
        nargs="?",
        help="Normalized IR output root. Legacy positional interface.",
    )

    parser.add_argument(
        "--data-root",
        help="Private kritva-forge-data repository root.",
    )
    parser.add_argument(
        "--rtl-root",
        help="Override RTL input root; defaults to <data-root>/raw/rtl/original.",
    )
    parser.add_argument(
        "--normalized-root",
        help="Override <data-root>/normalized/ir.",
    )
    parser.add_argument(
        "--datasets-root",
        help="Override <data-root>/datasets/pipeline.",
    )
    parser.add_argument(
        "--reports-root",
        help="Override <data-root>/analysis/reports.",
    )
    parser.add_argument(
        "--prompt-root",
        help="Override <data-root>/generated/prompts.",
    )
    parser.add_argument(
        "--curated-root",
        help="Optional curated prompt/RTL root.",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if args.data_root:
        data = ForgeDataPaths.from_root(args.data_root)
        rtl_root = args.rtl_root or str(data.raw_rtl / "original")
        normalized_root = args.normalized_root or str(data.normalized_ir)
        datasets_root = args.datasets_root or str(data.pipeline_datasets)
        reports_root = args.reports_root or str(data.reports)
        prompt_root = args.prompt_root or str(data.prompts)
    else:
        if args.legacy_out_root is None and args.rtl_root is None:
            print(
                "Usage: python -m scripts.pipeline.run_pipeline "
                "--data-root ../kritva-forge-data"
            )
            print(
                "   or: python -m scripts.pipeline.run_pipeline "
                "<rtl_root> <normalized_root>"
            )
            sys.exit(1)
    
        rtl_root = args.rtl_root or args.legacy_rtl_root
        normalized_root = args.normalized_root or args.legacy_out_root



        if not rtl_root or not normalized_root:
            print("Both rtl_root and normalized_root are required.")
            sys.exit(1)

        datasets_root = args.datasets_root
        reports_root = args.reports_root
        prompt_root = args.prompt_root

    run_pipeline(
        rtl_root,
        normalized_root,
        datasets_root=datasets_root,
        reports_root=reports_root,
        prompt_root=prompt_root,
        curated_root=args.curated_root,
        data_root=args.data_root,
    )


if __name__ == "__main__":
    main()
