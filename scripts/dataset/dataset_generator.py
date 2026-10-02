# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : dataset_generator.py
# Description : Dataset Generator implementation
#
# Component   : Kritva Forge
# Module      : dataset
# Layer       : Dataset
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
#--------------------------------------------------------------
#     File   : dataset_generator
#     Author : Dinesh Annayya
#     Date   : 6th June 2026
#     Purpose:  Generate LLM fine-tuning datasets.
#           combined
#            prompt        → RTL	RTL generation
#            yaml          → RTL	Structured RTL generation
#            hierarchy     → RTL	Top-level generation
#            RTL           → YAML	RTL understanding
#            RTL           → Hierarchy	Hierarchy extraction
#--------------------------------------------------------------
# Generated Json file format:  
#  {
#    "messages": [
#      {
#        "role": "user",
#        "content": "<prompt>"
#      },
#      {
#        "role": "assistant",
#        "content": "<actual RTL source>"
#      }
#    ]
#  }
#-------------------------------------------------------------
#   
#   out/
#   └── uart/
#       ├── hierarchy.yaml
#       ├── modules/
#       │   ├── uart_top.yaml
#       │   ├── uart_tx.yaml
#       │   └── uart_rx.yaml
#       ├── prompts/
#       │   ├── uart_top.txt
#       │   ├── uart_tx.txt
#       │   └── uart_rx.txt
#       ├── rtl/
#       │   ├── uart_top.v
#       │   ├── uart_tx.v
#       │   └── uart_rx.v
#       ├── dataset_prompt.jsonl
#       ├── dataset_yaml.jsonl
#       ├── dataset_hierarchy.jsonl
#       └── dataset_mixed.jsonl

#!/usr/bin/env python3

import os
import json
import random
import yaml
import re
import hashlib

TRAIN_RATIO = 0.70
VALID_RATIO = 0.15
TEST_RATIO  = 0.15

RANDOM_SEED = 42

USE_COMMENTS = True

CURATED_ROOT = "data/curated"
USE_CURATED = True
CURATED_VERBOSE = False

SKIP_IPS = {
    "common"
}

# --------------------------------------------------
# Helpers
# --------------------------------------------------

# File diffent prompt file, like
#  <module>.generate.txt
#  <module>.complete.txt
#  <module>.document.txt

def find_prompt_files(
        prompt_dir,
        module_name):

    files = []

    for f in os.listdir(
            prompt_dir):

        if not f.startswith(
                module_name + "."
        ):
            continue

        if not f.endswith(
                ".txt"
        ):
            continue

        files.append(
            os.path.join(
                prompt_dir,
                f
            )
        )

    return sorted(files)

# Check any curated prompt available at source path

def find_curated_prompt(
        ip,
        module,
        prompt_file):

    base = os.path.basename(
        prompt_file
    )

    path = os.path.join(
        CURATED_ROOT,
        ip,
        "prompts",
        base
    )

    return (
        path
        if os.path.exists(path)
        else None
    )


# Check any curated rtl  available at source path
def find_curated_rtl(
        ip,
        module):

    for ext in (
        ".sv",
        ".v"
    ):

        path = os.path.join(
            CURATED_ROOT,
            ip,
            "rtl",
            f"{module}{ext}"
        )

        if os.path.exists(
                path):

            return path

    return None

# Remove all the comments in RTL

def strip_comments(text):

    #
    # remove /* ... */
    #
    text = re.sub(
        r'/\*.*?\*/',
        '',
        text,
        flags=re.S
    )

    #
    # remove // ...
    #
    text = re.sub(
        r'//.*',
        '',
        text
    )

    return text

def percentile(values, pct):

    values = sorted(values)

    idx = int(
        len(values) * pct / 100
    )

    idx = min(
        idx,
        len(values) - 1
    )

    return values[idx]

# compute rtl status

def compute_rtl_stats(
        examples):

    rtl_line_counts = []
    rtl_char_counts = []
    top_module_count = 0

    largest_module = ""
    largest_chars = 0

    all_modules = set()
    top_modules = set()

    for ex in examples:

        mod_key = (
            f"{ex['ip']}/{ex['module']}"
        )

        all_modules.add(mod_key)

        if ex.get(
            "is_top",
            False):

            top_modules.add(mod_key)

        rtl = ex.get(
            "completion",
            ""
        )

        if len(rtl) > largest_chars:
        
            largest_chars = len(rtl)
        
            largest_module = ex.get(
                "module",
                ""
            )        

        line_count = len(
            rtl.splitlines()
        )

        rtl_line_counts.append(
            line_count
        )

        rtl_char_counts.append(
            len(rtl)
        )

    top_module_count = len(top_modules)

    leaf_module_count = ( len(all_modules) - top_module_count)

    if not rtl_line_counts:

        return {
            "largest_module": "",
            "min_rtl_lines": 0,
            "avg_rtl_lines": 0,
            "max_rtl_lines": 0,
            "avg_rtl_chars": 0,
            "max_rtl_chars": 0,
            "p50_rtl_chars": 0,
            "p90_rtl_chars": 0,
            "p95_rtl_chars": 0

        }

    return {

        "largest_module": largest_module,

        "min_rtl_lines":
            min(
                rtl_line_counts
            ),

        "avg_rtl_lines":
            round(
                sum(
                    rtl_line_counts
                )
                /
                len(
                    rtl_line_counts
                ),
                1
            ),

        "max_rtl_lines":
            max(
                rtl_line_counts
            ),
        "avg_rtl_chars":
            round(
                sum(rtl_char_counts)
                /
                len(rtl_char_counts),
                0
            ),

        "max_rtl_chars":
            max(rtl_char_counts),

        "p50_rtl_chars":
            percentile(
                rtl_char_counts,
                50
            ),
    
        "p90_rtl_chars":
            percentile(
                rtl_char_counts,
                90
            ),
    
        "p95_rtl_chars":
            percentile(
                rtl_char_counts,
                95
            ),

        "top_module_count": top_module_count,

        "leaf_module_count": leaf_module_count

            
            }

def load_text(path):

    with open(
        path,
        "r",
        encoding="utf-8",
        errors="ignore"
    ) as f:

        return f.read()

# --------------------------------------------------
# Save jsonl
# --------------------------------------------------

def save_jsonl(
        examples,
        path):

    with open(
        path,
        "w",
        encoding="utf-8"
    ) as f:

        for item in examples:

            f.write(
                json.dumps(
                    item,
                    ensure_ascii=False
                )
            )

            f.write("\n")

# --------------------------------------------------
# Save json
# --------------------------------------------------

def save_json(
        data,
        path):

    with open(
        path,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            indent=2
        )


# --------------------------------------------------
# Manifest helpers
# --------------------------------------------------

def compute_rtl_hash(text):

    return hashlib.sha256(
        text.encode("utf-8")
    ).hexdigest()


def load_manifest(path):

    if not os.path.exists(path):

        return {}

    with open(
        path,
        "r",
        encoding="utf-8"
    ) as f:

        return json.load(f)


def save_manifest(
        manifest,
        path):

    save_json(
        manifest,
        path
    )

#---------------------------------------------------
# Extract Task Type based on prompt file extension
#  <module>.generate.txt
#  <module>.complete.txt
#  <module>.document.txt
#---------------------------------------------------
def get_task_type(
        prompt_file):

    base = os.path.basename(
        prompt_file
    )

    parts = base.split(
        "."
    )

    #
    # <module>.generate.txt
    #
    if len(parts) < 3:

        return "rtl_generation"

    task = parts[-2]

    mapping = {

        "generate":
            "rtl_generation",

        "complete":
            "rtl_completion",

        "document":
            "rtl_documentation"
    }

    return mapping.get(
        task,
        "rtl_generation"
    )
# --------------------------------------------------
# Discover IPs
# --------------------------------------------------

def discover_ips(yaml_root):

    ips = []

    for name in sorted(
            os.listdir(yaml_root)
    ):

        #
        # Skip library/common folders
        #
        if name in SKIP_IPS:

            print(
                f"[INFO] Skipping IP: "
                f"{name}"
            )

            continue

        ip_dir = os.path.join(
            yaml_root,
            name
        )

        if not os.path.isdir(ip_dir):
            continue

        if not os.path.exists(
            os.path.join(
                ip_dir,
                "modules"
            )
        ):
            continue

        ips.append(ip_dir)

    return ips

# --------------------------------------------------
# Split IPs
# --------------------------------------------------

def split_ips(
        ip_dirs):

    random.seed(
        RANDOM_SEED
    )

    ip_dirs = list(
        ip_dirs
    )

    random.shuffle(
        ip_dirs
    )

    n = len(
        ip_dirs
    )

    train_end = int(
        n * TRAIN_RATIO
    )

    valid_end = int(
        n * (
            TRAIN_RATIO +
            VALID_RATIO
        )
    )

    train_ips = ip_dirs[
        :train_end
    ]

    valid_ips = ip_dirs[
        train_end:valid_end
    ]

    test_ips = ip_dirs[
        valid_end:
    ]

    return (
        train_ips,
        valid_ips,
        test_ips
    )


# --------------------------------------------------
# Locate RTL
# --------------------------------------------------

def find_matching_rtl(
        rtl_dir,
        module_name):

    candidates = [

        f"{module_name}.v",
        f"{module_name}.sv"
    ]

    for c in candidates:

        path = os.path.join(
            rtl_dir,
            c
        )

        if os.path.exists(
                path):
            return path

    return None


# --------------------------------------------------
# Build examples
# --------------------------------------------------

def build_examples_from_ip(
        ip_dir):

    examples = []

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

    for yaml_file in sorted(
        os.listdir(
            modules_dir
        )
    ):

        if not yaml_file.endswith(
                ".yaml"):
            continue
 
        module_name = os.path.splitext(
            yaml_file
        )[0]
        
        spec = yaml.safe_load(
            load_text(
                os.path.join(
                    modules_dir,
                    yaml_file
                )
            )
        )

        assign_count = len(
            spec.get("assigns", [])
        )
        rtl_file = spec.get(
            "source_file"
        )

        prompt_files = (
            find_prompt_files(
                prompts_dir,
                module_name
            )
        )
        
        if not prompt_files:
        
            #
            # backward compatibility
            #
            old_prompt = os.path.join(
                prompts_dir,
                f"{module_name}.txt"
            )
        
            if os.path.exists(
                    old_prompt):
        
                prompt_files = [
                    old_prompt
                ]
        
        if not prompt_files:
            continue


        #
        # Prefer curated RTL
        #
        curated_rtl = None
        
        if USE_CURATED:
        
            curated_rtl = (
                find_curated_rtl(
                    ip_name,
                    module_name
                )
            )
        
        if curated_rtl:
            if CURATED_VERBOSE:
                print(
                    f"[INFO] Using curated RTL "
                    f"{module_name}"
                )
        
            rtl_file = (
                curated_rtl
            )

        if not rtl_file:
        
            print(
                f"[WARN] No source_file "
                f"for {module_name}"
            )
        
            continue
        
        if not os.path.exists(
                rtl_file):
        
            print(
                f"[WARN] Missing RTL "
                f"{rtl_file}"
            )
        
            continue

        rtl = load_text(
            rtl_file
        )

        if not USE_COMMENTS:
            rtl = strip_comments(
                rtl
            )

        for prompt_file in prompt_files:

            curated_prompt = (
                find_curated_prompt(
                    ip_name,
                    module_name,
                    prompt_file
                )
            )
        
            task_type = get_task_type(
                prompt_file
            )
            if curated_prompt:
            
                prompt = load_text(
                    curated_prompt
                )
            
            else:
            
                prompt = load_text(
                    prompt_file
                )

            examples.append({
            
                "prompt_source":
                    "curated"
                    if curated_prompt
                    else "generated",
            
                "rtl_source":
                    "curated"
                    if curated_rtl
                    else "generated",
            
                "task":
                    task_type,
            
                "prompt_variant":
                    os.path.basename(
                        prompt_file
                    ),
            
                "ip":
                    ip_name,
            
                "module":
                    module_name,
            
                "is_top":
                    spec.get(
                        "is_top",
                        False
                    ),
            
                "prompt":
                    prompt,
            
                "completion":
                    rtl
            })


    return examples


# --------------------------------------------------
# Build dataset
# --------------------------------------------------

def build_dataset(
        ip_dirs):

    dataset = []

    for ip_dir in ip_dirs:

        dataset.extend(
            build_examples_from_ip(
                ip_dir
            )
        )

    return dataset


# --------------------------------------------------
# Classify modules
# --------------------------------------------------
def classify_examples(
        examples,
        manifest):

    new_examples = []
    old_examples = []

    new_count = 0
    modified_count = 0
    unchanged_count = 0

    new_manifest = {}

    for ex in examples:

        rtl_hash = compute_rtl_hash(
            ex["prompt"] +
            ex["completion"]
        )

        key = (
        
            f"{ex['ip']}/"
            f"{ex['module']}/"
            f"{ex['task']}/"
            f"{ex['prompt_variant']}"
        )

        new_manifest[key] = rtl_hash

        old_hash = manifest.get(
            key
        )

        if old_hash is None:

            ex["change_type"] = "new"

            new_examples.append(
                ex
            )

            new_count += 1

        elif old_hash != rtl_hash:

            ex["change_type"] = (
                "modified"
            )

            new_examples.append(
                ex
            )

            modified_count += 1

        else:

            ex["change_type"] = (
                "unchanged"
            )

            old_examples.append(
                ex
            )

            unchanged_count += 1

    return (
        new_examples,
        old_examples,
        new_manifest,
        new_count,
        modified_count,
        unchanged_count
    )
# --------------------------------------------------
# Stats
# --------------------------------------------------

def build_stats(
        train,
        validation,
        test):

    all_examples = (
        train
        + validation
        + test
    )

    task_breakdown = {}
    
    for ex in (
            train
            + validation
            + test):
    
        task = ex["task"]
    
        task_breakdown[task] = (
    
            task_breakdown.get(
                task,
                0
            )
    
            + 1
        )

    total_assigns = sum(
        ex.get("assign_count", 0)
        for ex in all_examples
    )

    variant_breakdown = {}

    for ex in all_examples:
    
        name = ex["prompt_variant"]


        parts = name.split(".")
        
        if len(parts) >= 3:
            suffix = parts[-2]
        else:
            suffix = "legacy"

        variant_breakdown[suffix] = (
            variant_breakdown.get(
                suffix,
                0
            ) + 1
        )
    
    stats = {

        "pipeline_version": "v1",
    
        "train_examples":
            len(train),
    
        "validation_examples":
            len(validation),
    
        "test_examples":
            len(test),
    
        "total_examples":
            len(train)
            + len(validation)
            + len(test),

        "task_breakdown": task_breakdown,

        "variant_breakdown" : variant_breakdown,
        
        "prompt_variants": sorted(
            variant_breakdown.keys()
        )


    }
    return  stats


# --------------------------------------------------
# Main
# --------------------------------------------------

def generate_datasets(
        yaml_root,
        out_dir):

    os.makedirs(
        out_dir,
        exist_ok=True
    )

    manifest_file = os.path.join(
        out_dir,
        "manifest.json"
    )
    
    old_manifest = load_manifest(
        manifest_file
    )

    ip_dirs = discover_ips(
        yaml_root
    )

    print(
        f"[INFO] Found "
        f"{len(ip_dirs)} IPs"
    )

    train_ips, \
    valid_ips, \
    test_ips = split_ips(
        ip_dirs
    )

    print(
        f"[INFO] Train IPs      : "
        f"{len(train_ips)}"
    )

    print(
        f"[INFO] Validation IPs : "
        f"{len(valid_ips)}"
    )

    print(
        f"[INFO] Test IPs       : "
        f"{len(test_ips)}"
    )

    train = build_dataset(
        train_ips
    )

    validation = build_dataset(
        valid_ips
    )

    test = build_dataset(
        test_ips
    )

    all_examples = (
        train
        + validation
        + test
    )

    curated_examples = sum(
        1
        for ex in all_examples
    
        if (
            ex.get(
                "prompt_source"
            ) == "curated"
            or
            ex.get(
                "rtl_source"
            ) == "curated"
        )
    )
    
    generated_examples = (
    
        len(all_examples)
    
        - curated_examples
    )


    new_examples, \
    old_examples, \
    new_manifest, \
    new_count, \
    modified_count, \
    unchanged_count = classify_examples(
        all_examples,
        old_manifest
    ) 

    rtl_stats = compute_rtl_stats(
        all_examples
    )
    mixed = (
        train +
        validation +
        test
    )

    save_jsonl(
        train,
        os.path.join(
            out_dir,
            "train.jsonl"
        )
    )

    save_jsonl(
        validation,
        os.path.join(
            out_dir,
            "validation.jsonl"
        )
    )

    save_jsonl(
        test,
        os.path.join(
            out_dir,
            "test.jsonl"
        )
    )

    save_jsonl(
        mixed,
        os.path.join(
            out_dir,
            "dataset_mixed.jsonl"
        )
    )

    save_jsonl(
        new_examples,
        os.path.join(
            out_dir,
            "dataset_new.jsonl"
        )
    )
    
    save_jsonl(
        old_examples,
        os.path.join(
            out_dir,
            "dataset_old.jsonl"
        )
    )

    stats = build_stats(
        train,
        validation,
        test
    )
    
    stats.update(
        rtl_stats
    )

    stats.update({
    
        "curated_examples":
            curated_examples,
    
        "generated_examples":
            generated_examples
    
    })

    new_module_set = set()
    modified_module_set = set()
    
    for ex in new_examples:
    
        if ex["change_type"] == "new":
    
            new_module_set.add(
                f"{ex['ip']}/{ex['module']}"
            )
    
        elif ex["change_type"] == "modified":
    
            modified_module_set.add(
                f"{ex['ip']}/{ex['module']}"
            )

    all_module_set = set(
        f"{ex['ip']}/{ex['module']}"
        for ex in all_examples
    )
    
    changed_module_set = (
        new_module_set
        | modified_module_set
    )
       
    old_module_count = (
        len(all_module_set)
        - len(changed_module_set)
    )

    stats.update({
    
        "new_examples":
            new_count,
    
        "modified_examples":
            modified_count,
    
        "new_or_modified_examples":
            len(new_examples),
    
        "old_examples":
            unchanged_count,
    
        "new_modules":
            len(new_module_set),
    
        "modified_modules":
            len(modified_module_set),
    
        "old_modules":
            old_module_count
    })
    
    save_manifest(
        new_manifest,
        manifest_file
    )
    
    save_json(
        stats,
        os.path.join(
            out_dir,
            "dataset_stats.json"
        )
    )

    print(
        f"[INFO] New          : "
        f"{new_count}"
    )
    
    print(
        f"[INFO] Modified     : "
        f"{modified_count}"
    )
    
    print(
        f"[INFO] New/Modified : "
        f"{len(new_examples)}"
    )
    
    print(
        f"[INFO] Unchanged    : "
        f"{unchanged_count}"
    )

    print(
        f"[INFO] Train      : "
        f"{len(train)}"
    )

    print(
        f"[INFO] Validation : "
        f"{len(validation)}"
    )

    print(
        f"[INFO] Test       : "
        f"{len(test)}"
    )

    dataset_yaml_count = 0
   
    for ip_dir in ip_dirs:
    
        modules_dir = os.path.join(
            ip_dir,
            "modules"
        )
    
        dataset_yaml_count += len(
            [
                f
                for f in os.listdir(
                    modules_dir
                )
                if f.endswith(
                    ".yaml"
                )
            ]
        )
    
    total_examples = len(train) + len(validation) + len(test)

    if dataset_yaml_count:
    
        expansion_factor = (
            total_examples
            / dataset_yaml_count
        )
        print(
            f"[INFO] YAMLs     : "
            f"{dataset_yaml_count}"
        )
        
        print(
            f"[INFO] Prompt Expansion  : "
            f"{expansion_factor:.1f}x"
        )


if __name__ == "__main__":

    import sys

    if len(sys.argv) != 3:

        print(
            "Usage: "
            "dataset_generator.py "
            "<yaml_root> "
            "<out_dir>"
        )

        sys.exit(1)

    generate_datasets(
        sys.argv[1],
        sys.argv[2]
    )
