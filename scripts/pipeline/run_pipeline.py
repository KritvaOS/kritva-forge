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
#     File   : run_pipeline
#     Author : Dinesh Annayya
#     Date   :  6th June 2026
#     Reference: https://chatgpt.com/c/6a242fb9-bbcc-8323-b4c2-997a95fea512
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
#       <Rev0.1> <7June 2026><Dinesh Annayya> 
#           ✅ Skip common/
#           ✅ Support filelist (files.f) flow
#           ✅ Better logging
#           ✅ Dataset statistics
#           ✅ Dataset folder creation
#           ✅ Per-IP summary
#           ✅ Graceful error handling
#---------------------------------------------------------
#  Expected input data folder structure with filelist
#     data/raw_rtl/
#      ├── common/
#      │   ├── sync_fifo.v
#      │   ├── async_fifo.v
#      │   └── reset_sync.v
#      │
#      ├── uart/
#      │   ├── files.f
#      │   ├── uart_top.v
#      │   ├── uart_tx.v
#      │   ├── uart_rx.v
#      │   └── uart_baudrate.v
#      │
#      ├── spi/
#      │   ├── files.f
#      │   ├── spi_top.v
#      │   └── spi_master.v
#      │
#      └── i2c/
#          ├── files.f
#          ├── i2c_top.v
#          └── i2c_master.v
# Command
#  python scripts/run_pipeline.py \
#    data/raw_rtl \
#    out
#--------------------------------------------------------------
#   run_pipeline.py
#   
#   RTL -> YAML -> Dataset pipeline
#   
#   Usage:
#       python scripts/run_pipeline.py \
#           data/raw_rtl \
#           out
#--------------------------------------------------------------

import json
import os
import sys
import traceback

from scripts.parser.rtl_parser_slang import parse_ip
from scripts.dataset.yaml_generator import write_ip_outputs
from scripts.dataset.dataset_generator import generate_datasets
from scripts.parser.statistics import print_summary
from scripts.pipeline.run_semantic import run_semantic

import logging

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s",
)

GENERATE_DATASETS = True

ENABLE_SEMANTIC = True


def discover_ips(rtl_root):
    """
    Discover RTL compilation units.

    If rtl_root itself contains files.f, treat it as a
    single compilation unit. Otherwise discover child
    directories as before.
    """

    if os.path.isfile(
        os.path.join(rtl_root, "files.f")
    ):
        return [rtl_root]

    ips = []

    for name in sorted(os.listdir(rtl_root)):

        ip_dir = os.path.join(
            rtl_root,
            name
        )

        if not os.path.isdir(ip_dir):
            continue

        ips.append(ip_dir)

    return ips


def process_ip(
        ip_dir,
        out_root):
    """
    Process a single IP.
    """

    ip_name = os.path.basename(
        ip_dir
    )

    print(
        f"\n{'=' * 60}"
    )

    print(
        f"[INFO] Processing IP: "
        f"{ip_name}"
    )

    print(
        f"{'=' * 60}"
    )

    #
    # Parse RTL
    #
    modules, top = parse_ip(
        ip_dir
    )

    semantic_ctx = None
    
    if ENABLE_SEMANTIC:
        semantic_ctx = run_semantic(modules)


    #
    # Generate YAML + prompts
    #
    write_ip_outputs(
        ip_name,
        modules,
        top,
        out_root,
        semantic_ctx=semantic_ctx,
    )

    return {
        "ip": ip_name,
        "top": top,
        "modules": len(modules),
        "semantic": semantic_ctx,
    }


def save_pipeline_stats(
        results,
        out_root):
    """
    Save pipeline statistics.
    """

    stats = {

        "ips":

            len(results),

        "modules":

            sum(
                r["modules"]
                for r in results
            ),

        "top_modules": {

            r["ip"]:
            r["top"]

            for r in results
        }
    }

    with open(
        os.path.join(
            out_root,
            "pipeline_stats.json"
        ),
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            stats,
            f,
            indent=2
        )


def print_pipeline_summary(
        results):
    """
    Print final summary.
    """

    print(
        "\n"
        + "=" * 60
    )

    print(
        "PIPELINE SUMMARY"
    )

    print(
        "=" * 60
    )

    print(
        f"IPs processed : "
        f"{len(results)}"
    )

    print(
        f"Modules       : "
        f"{sum(r['modules'] for r in results)}"
    )

    print(
        "\nTop Modules:"
    )

    for r in results:

        print(
            f"  {r['ip']:20s}"
            f" -> "
            f"{r['top']}"
        )


def run_pipeline(
        rtl_root,
        out_root):
    """
    Run complete pipeline.
    """

    os.makedirs(
        out_root,
        exist_ok=True
    )

    ips = discover_ips(
        rtl_root
    )

    print(
        f"[INFO] Found "
        f"{len(ips)} IPs"
    )

    results = []

    for ip_dir in ips:

        try:

            result = process_ip(
                ip_dir,
                out_root
            )

            results.append(
                result
            )
        except Exception as e:

            print("\n" + "=" * 80)
            print("[PIPELINE ERROR]")
            print("IP Directory :", ip_dir)
            print("Exception    :", type(e).__name__)
            print("Message      :", e)
            print("-" * 80)

            traceback.print_exc()

            print("=" * 80)

            raise


    #
    # Save stats
    #
    save_pipeline_stats(
        results,
        out_root
    )

    #
    # Generate datasets
    #
    if GENERATE_DATASETS:

        print(
            "\n"
            + "=" * 60
        )

        print(
            "[INFO] Generating datasets"
        )

        print(
            "=" * 60
        )

        generate_datasets( out_root, os.path.join( out_root, "datasets"))

    print_pipeline_summary( results)

    print_summary()

    return results


def main():

    if len(sys.argv) != 3:
        print( "\nUsage:\n")
        print( "python " "scripts/run_pipeline.py " "<rtl_root> " "<out_root>\n")
        sys.exit(1)

    rtl_root = sys.argv[1]
    out_root = sys.argv[2]

    run_pipeline(
        rtl_root,
        out_root
    )


if __name__ == "__main__":
    main()
