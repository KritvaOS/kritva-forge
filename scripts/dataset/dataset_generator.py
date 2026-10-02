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
#   normalized/ir/<ip>/
#   └── uart/
#       ├── hierarchy.yaml
#       ├── modules/
#       │   ├── uart_top.yaml
#       │   ├── uart_tx.yaml
#       │   └── uart_rx.yaml
#       ├── prompts/  (legacy co-located mode)
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
import yaml
import re
import hashlib

from scripts.dataset.leakage import (
    SPLITS,
    assign_splits,
    build_manifest,
    check_leakage,
    compute_identities,
    format_report,
)
from scripts.core.provenance import (
    record_provenance,
    sha256_file,
)
from scripts.core.paths import (
    ForgeDataPaths,
    infer_data_root,
    iter_ip_dirs,
    iter_module_yamls,
    resolve_provenance_path,
    to_provenance_path,
)

TRAIN_RATIO = 0.70
VALID_RATIO = 0.15
TEST_RATIO  = 0.15


USE_COMMENTS = True

CURATED_ROOT = os.environ.get("KRITVA_FORGE_CURATED_ROOT", "")
USE_CURATED = bool(CURATED_ROOT)
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
        prompt_file,
        curated_root=None):

    base = os.path.basename(
        prompt_file
    )

    root = curated_root or CURATED_ROOT
    if not root:
        return None

    path = os.path.join(
        root,
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
        module,
        curated_root=None):

    for ext in (
        ".sv",
        ".v"
    ):

        root = curated_root or CURATED_ROOT
        if not root:
            return None
        path = os.path.join(
            root,
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

def _is_within(path, root):
    try:
        to_provenance_path(path, root)
        return True
    except ValueError:
        return False


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
    """Return canonical IP dirs (``<ip>/modules/`` present), sorted (KF-DQ-001)."""

    ips = []

    for ip_dir in iter_ip_dirs(yaml_root):

        #
        # Skip library/common folders
        #
        if ip_dir.name in SKIP_IPS:

            print(
                f"[INFO] Skipping IP: "
                f"{ip_dir.name}"
            )

            continue

        ips.append(str(ip_dir))

    return ips

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
        ip_dir,
        prompt_root=None,
        curated_root=None):

    examples = []

    ip_name = os.path.basename(
        ip_dir
    )

    modules_dir = os.path.join(
        ip_dir,
        "modules"
    )

    if prompt_root:
        prompts_dir = os.path.join(
            prompt_root,
            ip_name
        )
    else:
        prompts_dir = os.path.join(
            ip_dir,
            "prompts"
        )

    for yaml_path in iter_module_yamls(
        os.path.dirname(ip_dir),
        ip_name,
    ):

        yaml_file = yaml_path.name
 
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
        source_rel = rtl_file
        data_root = infer_data_root(ip_dir)

        #
        # KF-DQ-002: persisted provenance is repository-relative
        # (raw/rtl/original/...); resolve it against the data root that
        # contains this IR tree.
        #
        if rtl_file and not os.path.isabs(rtl_file):
            if data_root is not None:
                rtl_file = str(
                    resolve_provenance_path(rtl_file, data_root)
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
                    module_name,
                    curated_root=curated_root
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
        source_text = rtl

        #
        # KF-DQ-005: provenance of every record from this module.
        # The source is always the IR's original RTL; curated RTL (if used
        # as the completion) is recorded as a separate artifact.
        #
        yaml_abs = os.path.join(modules_dir, yaml_file)
        if data_root is not None and source_rel and not os.path.isabs(source_rel):
            source_abs = str(resolve_provenance_path(source_rel, data_root))
            ir_rel = to_provenance_path(yaml_abs, data_root)
        else:
            source_abs = rtl_file if not curated_rtl else None
            ir_rel = None
        provenance_args = {
            "source_path": source_rel,
            "source_sha256": sha256_file(source_abs) if source_abs and os.path.exists(source_abs) else None,
            "ir_path": ir_rel,
            "ir_sha256": sha256_file(yaml_abs),
            "generated_artifact": (
                {
                    "type": "curated",
                    "path": (
                        to_provenance_path(curated_rtl, data_root)
                        if data_root is not None and _is_within(curated_rtl, data_root)
                        else os.path.basename(curated_rtl)
                    ),
                    "sha256": sha256_file(curated_rtl),
                }
                if curated_rtl else None
            ),
        }

        if not USE_COMMENTS:
            rtl = strip_comments(
                rtl
            )

        for prompt_file in prompt_files:

            curated_prompt = (
                find_curated_prompt(
                    ip_name,
                    module_name,
                    prompt_file,
                    curated_root=curated_root
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
            
                # KF-DQ-005: the completion is the original RTL unless a
                # curated RTL file replaced it (was mislabelled "generated").
                "rtl_source":
                    "curated"
                    if curated_rtl
                    else "original",
            
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

            examples[-1]["provenance"] = record_provenance(
                examples[-1],
                **provenance_args,
            )

            # KF-DQ-004: leakage identities (internal; not written to jsonl)
            examples[-1]["_leakage"] = compute_identities(
                examples[-1],
                spec,
                source_text,
            )


    return examples


# --------------------------------------------------
# Build dataset
# --------------------------------------------------

def build_dataset(
        ip_dirs,
        prompt_root=None,
        curated_root=None):

    dataset = []

    for ip_dir in ip_dirs:

        dataset.extend(
            build_examples_from_ip(
                ip_dir,
                prompt_root=prompt_root,
                curated_root=curated_root
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
        out_dir,
        prompt_root=None,
        curated_root=None,
        splits_root=None,
        reports_root=None):

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

    #
    # KF-DQ-004: leakage-safe deterministic split.
    # Build every example (IPs in sorted order), group records that share
    # any hard content identity, and assign groups atomically
    # (scripts/dataset/leakage.py documents the policy).
    #
    candidates = build_dataset(
        ip_dirs,
        prompt_root=prompt_root,
        curated_root=curated_root
    )

    identities = [
        ex["_leakage"]
        for ex in candidates
    ]

    assignment, groups = assign_splits(
        identities
    )

    by_split = {
        split: [
            ex
            for ex in candidates
            if assignment[ex["_leakage"]["record_id"]] == split
        ]
        for split in SPLITS
    }

    train = by_split["train"]
    validation = by_split["validation"]
    test = by_split["test"]

    split_manifest = build_manifest(
        candidates,
        identities,
        assignment,
        groups
    )

    leakage_report = check_leakage(
        {
            split: [ex["_leakage"] for ex in by_split[split]]
            for split in SPLITS
        },
        split_manifest
    )

    print(format_report(leakage_report))

    for ex in candidates:
        ex.pop("_leakage", None)

    if splits_root is None or reports_root is None:
        data_root = infer_data_root(yaml_root)
        if data_root is not None:
            data = ForgeDataPaths.from_root(data_root)
            splits_root = splits_root or str(data.splits)
            reports_root = reports_root or str(data.reports)

    if splits_root:
        os.makedirs(splits_root, exist_ok=True)
        save_json(
            split_manifest,
            os.path.join(splits_root, "split_manifest.json")
        )

    if reports_root:
        os.makedirs(reports_root, exist_ok=True)
        save_json(
            leakage_report,
            os.path.join(reports_root, "split_leakage_report.json")
        )

    if leakage_report["status"] != "PASS":
        raise RuntimeError(
            "split leakage check failed (KF-DQ-004): "
            + "; ".join(leakage_report["problems"])
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
    
        dataset_yaml_count += len(
            list(
                iter_module_yamls(
                    os.path.dirname(ip_dir),
                    os.path.basename(ip_dir),
                )
            )
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

    if len(sys.argv) not in (3, 4, 5):

        print(
            "Usage: dataset_generator.py "
            "<yaml_root> <out_dir> "
            "[prompt_root] [curated_root]"
        )

        sys.exit(1)

    generate_datasets(
        sys.argv[1],
        sys.argv[2],
        prompt_root=sys.argv[3] if len(sys.argv) >= 4 else None,
        curated_root=sys.argv[4] if len(sys.argv) >= 5 else None,
    )
