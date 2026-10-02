#!/usr/bin/env python3
# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : bootstrap_curated.py
# Description : Bootstrap Curated implementation
#
# Component   : Kritva Forge
# Module      : dataset
# Layer       : Dataset
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
# --------------------------------------------------------------
# bootstrap_curated.py
#
# Populate an explicitly selected curated/golden data root from generated artifacts.
#
# Copies:
#   normalized/ir/<ip>/prompts/*.txt
#       -> <curated_root>/<ip>/prompts/
#
#   source RTL referenced by module YAML
#       -> <curated_root>/<ip>/rtl/
#
# Existing curated files are NEVER overwritten.
#-----------------------------------------------------------------
#       ✅ Multi-prompt support
#       ✅ Curated prompt protection
#       ✅ Curated RTL protection
#       ✅ Efficient prompt lookup
#       ✅ Accurate copied/existing statistics
#       ✅ Proper directory validation
#       ✅ Backward compatible with module.txt.
#       ✅ Supports multi-prompt format.
#       ✅ Efficient lookup implementation.
#       ✅ Deterministic file ordering.
#       ✅ Accurate copied/existing counters.
# --------------------------------------------------------------

import os
import shutil
import yaml
from collections import defaultdict

from scripts.core.paths import iter_module_yamls


CURATED_ROOT = os.environ.get("KRITVA_FORGE_CURATED_ROOT", "")


def load_yaml(path):

    with open(
        path,
        "r",
        encoding="utf-8"
    ) as f:

        return yaml.safe_load(
            f
        )


def copy_if_missing(
        src,
        dst):

    if not os.path.exists(
            src):
        return False

    if os.path.exists(
            dst):
        return False

    os.makedirs(
        os.path.dirname(
            dst
        ),
        exist_ok=True
    )

    shutil.copy2(
        src,
        dst
    )

    return True


def process_ip(
        ip_dir,
        curated_root):

    prompt_copied = 0
    prompt_existing = 0
    
    rtl_copied = 0
    rtl_existing = 0

    ip_name = os.path.basename(
        ip_dir
    )

    modules_dir = os.path.join(
        ip_dir,
        "modules"
    )

    prompts_dir = os.path.join(
        ip_dir,
        "prompts"
    )

    if not os.path.isdir(
            modules_dir):
        return (0, 0, 0, 0)

    if not os.path.isdir(
            prompts_dir):
        return (0, 0, 0, 0)

    all_prompt_files = sorted(
        os.listdir(
            prompts_dir
        )
    )

    prompt_map = defaultdict(list)
    
    for prompt_file in all_prompt_files:
    
        if not prompt_file.endswith(
                ".txt"):
            continue
    
        parts = prompt_file.split(
            "."
        )
    
        #
        # uart_tx.generate.txt
        #
        if len(parts) == 2:
        
            module_name = parts[0]
        
        elif len(parts) >= 3:
        
            module_name = ".".join(
                parts[:-2]
            )
        
        else:
            continue

    
        prompt_map[module_name].append(
            prompt_file
        )


    for yaml_path in iter_module_yamls(
            os.path.dirname(ip_dir),
            ip_name,
    ):

        yaml_file = yaml_path.name

        module_name = os.path.splitext(
            yaml_file
        )[0]

        yaml_path = os.path.join(
            modules_dir,
            yaml_file
        )

        spec = load_yaml(
            yaml_path
        )

        #
        # --------------------------------------------------
        # Prompt
        # --------------------------------------------------
        #

        for prompt_file in sorted(
                prompt_map.get(
                    module_name,
                    []
                )
        ):
        
            prompt_src = os.path.join(
                prompts_dir,
                prompt_file
            )
        
            prompt_dst = os.path.join(
                curated_root,
                ip_name,
                "prompts",
                prompt_file
            )

            if os.path.exists(
                    prompt_dst):
            
                prompt_existing += 1
            
            elif copy_if_missing(
                    prompt_src,
                    prompt_dst):
            
                prompt_copied += 1
        
        #
        # --------------------------------------------------
        # RTL
        # --------------------------------------------------
        #
        rtl_src = spec.get(
            "source_file"
        )

        if rtl_src and os.path.exists(
                rtl_src):

            ext = os.path.splitext(
                rtl_src
            )[1]

            rtl_dst = os.path.join(
                curated_root,
                ip_name,
                "rtl",
                f"{module_name}{ext}"
            )

            if os.path.exists(
                    rtl_dst):
            
                rtl_existing += 1
            
            elif copy_if_missing(
                    rtl_src,
                    rtl_dst):
            
                rtl_copied += 1

    return (
        prompt_copied,
        prompt_existing,
        rtl_copied,
        rtl_existing
    )


def main():

    import sys

    if len(sys.argv) not in (2, 3):

        print(
            "Usage: bootstrap_curated.py "
            "<out_dir> [curated_root]"
        )

        sys.exit(1)

    out_root = sys.argv[1]
    curated_root = sys.argv[2] if len(sys.argv) == 3 else CURATED_ROOT

    if not curated_root:
        print("[ERROR] curated_root is required")
        sys.exit(1)

    total_prompt_copied = 0
    total_prompt_existing = 0
    
    total_rtl_copied = 0
    total_rtl_existing = 0

    for name in sorted(
            os.listdir(
                out_root
            )
    ):

        ip_dir = os.path.join(
            out_root,
            name
        )

        if not os.path.isdir(
                ip_dir):
            continue

        if not os.path.isdir(
                os.path.join(
                    ip_dir,
                    "prompts"
                )
        ):
            continue

        if not os.path.isdir(
            os.path.join(
                ip_dir,
                "modules"
            )
        ):
            continue


        prompt_copied, \
        prompt_existing, \
        rtl_copied, \
        rtl_existing = (
            process_ip(ip_dir, curated_root)
        )

        total_prompt_copied += prompt_copied
        total_prompt_existing += prompt_existing
        
        total_rtl_copied += rtl_copied
        total_rtl_existing += rtl_existing

        print(
            f"[INFO] {name:<20}"
            f" copied_prompts={prompt_copied:<4}"
            f" existing_prompts={prompt_existing:<4}"
            f" copied_rtls={rtl_copied:<4}"
            f" existing_rtls={rtl_existing:<4}"
        )


    print()
    print(
        f"[INFO] Copied Prompts   : "
        f"{total_prompt_copied}"
    )
    
    print(
        f"[INFO] Existing Prompts : "
        f"{total_prompt_existing}"
    )
    
    print(
        f"[INFO] Copied RTLs      : "
        f"{total_rtl_copied}"
    )
    
    print(
        f"[INFO] Existing RTLs    : "
        f"{total_rtl_existing}"
    )


if __name__ == "__main__":

    main()
