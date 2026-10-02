#!/usr/bin/env python3
# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : fsm_report.py
# Description : Fsm Report implementation
#
# Component   : Kritva Forge
# Module      : analysis
# Layer       : Analysis
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
# ----------------------------------------------------
# fsm_report.py
# 
# Generate FSM coverage reports from parser YAML output.
# 
# Usage:
# python scripts/fsm_report.py out reports
# -----------------------------------------------------

import os
import csv
import sys
import yaml

IGNORE_FILES = {
    "hierarchy",
    "summary",
    "index",
    "manifest"
}

# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

def is_non_fsm_module(name):

    name = name.lower()

    patterns = [
        "buf",
        "mux",
        "sync",
        "register",
        "fifo",
        "ram",
        "rom",
        "gate",
        "dff"
    ]

    return any(
        name.startswith(p)
        or f"_{p}" in name
        for p in patterns
    )

def get_module_name(data, path):

    return (
        data.get("module_name")
        or data.get("module")
        or os.path.basename(path).replace(
            ".yaml",
            ""
        )
    )

def load_yaml(path):

    try:
    
        with open(path, "r") as fp:
            return yaml.safe_load(fp)
    
    except Exception:
    
        return None


def collect_modules(out_dir):
    modules = []
    
    for root, _, files in os.walk(out_dir):

        for f in files:

            if not f.endswith(".yaml"):
                continue

            #
            # Skip report/helper files
            #
            stem = os.path.splitext(f)[0]

            if stem in IGNORE_FILES:
                continue

            path = os.path.join(root, f)

            data = load_yaml(path)

            if not data:
                continue

            # Ignore bogus module
            module_name = get_module_name(data,path)

            if module_name in IGNORE_FILES:
                continue

            modules.append(
                (path, data)
            )


    return modules

# ------------------------------------------------------------
# FSM CSV Report
# ------------------------------------------------------------

def generate_fsm_report(modules, report_csv):

    rows = []

    if not modules:
        print(
            "[ERROR] No YAML files found"
        )
        sys.exit(1)
    
    for path, data in modules:
    
        fsm = data.get("fsm", {})

        row = {

            "module": get_module_name (data,path),

            "style":
                fsm.get(
                    "style"
                ),

            "state_reg":
                fsm.get(
                    "state_reg"
                ),

            "next_state":
                fsm.get(
                    "next_state"
                ),

            "reset_state":
                fsm.get(
                    "reset_state"
                ),

            "num_states":
                len(
                    fsm.get(
                        "states",
                        []
                    )
                ),

            "num_transitions":
                len(
                    fsm.get(
                        "transitions",
                        []
                    )
                ),

            "confidence":
                fsm.get(
                    "confidence",
                    "low"
                )
        }
    
        rows.append(row)
    

    conf_rank = {
        "high": 3,
        "medium": 2,
        "low": 1
    }

    rows.sort(
        key=lambda x: (
            conf_rank.get(
                x["confidence"],
                0
            ),
            x["num_states"],
            x["num_transitions"]
        ),
        reverse=True
    )

    
    with open(
        report_csv,
        "w",
        newline=""
    ) as fp:
    
        writer = csv.DictWriter(
            fp,
            fieldnames=[
                "module",
                "style",
                "state_reg",
                "next_state",
                "reset_state",
                "num_states",
                "num_transitions",
                "confidence"
            ]
        )
    
        writer.writeheader()
    
        for row in rows:
            writer.writerow(row)
    
    return rows

# ------------------------------------------------------------
# Summary Report
# ------------------------------------------------------------

def generate_summary(rows, summary_file):

    total_modules = len(rows)

    fsm_modules = [
        r
        for r in rows
        if (
            r["state_reg"]
            and
            r["num_states"] > 0
        )
    ]
    
    high = sum(
        1
        for r in rows
        if r["confidence"] == "high"
    )
    
    medium = sum(
        1
        for r in rows
        if r["confidence"] == "medium"
    )
    
    low = sum(
        1
        for r in rows
        if r["confidence"] == "low"
    )
    
    avg_states = 0.0
    avg_transitions = 0.0
    
    if fsm_modules:
    
        avg_states = (
            sum(
                r["num_states"]
                for r in fsm_modules
            )
            /
            len(fsm_modules)
        )

        avg_transitions = (

            sum(
                r["num_transitions"]
                for r in fsm_modules
            ) /

            len(fsm_modules)
        )


    
    largest = None
    
    if fsm_modules:
    
        largest = max(
            fsm_modules,
            key=lambda r:
                r["num_states"]
        )
    
    with open(
        summary_file,
        "w"
    ) as fp:
    
        fp.write(
            "FSM EXTRACTION SUMMARY\n"
        )
    
        fp.write(
            "=" * 60 + "\n\n"
        )
    
        fp.write(
            f"Total modules            : {total_modules}\n"
        )
    
        fp.write(
            f"FSMs detected            : {len(fsm_modules)}\n"
        )

        fp.write(
            f"FSM coverage             : "
            f"{100.0 * len(fsm_modules) / max(total_modules,1):.1f}%\n"
        )
    
        fp.write(
            f"High confidence FSMs     : {high}\n"
        )
    
        fp.write(
            f"Medium confidence FSMs   : {medium}\n"
        )
    
        fp.write(
            f"Low confidence FSMs      : {low}\n"
        )
   
        fp.write(
            f"Average states/FSM       : "
            f"{avg_states:.2f}\n"
        )

        fp.write(
            f"Average transitions/FSM : "
            f"{avg_transitions:.2f}\n"
        )
    
        if largest:
    
            fp.write("\n")
    
            fp.write(
                "Largest FSM\n"
            )
    
            fp.write(
                "-" * 40 + "\n"
            )
    
            fp.write(
                f"Module                  : "
                f"{largest['module']}\n"
            )
    
            fp.write(
                f"States                  : "
                f"{largest['num_states']}\n"
            )
    
            fp.write(
                f"Transitions             : "
                f"{largest['num_transitions']}\n"
            )

# ------------------------------------------------------------
# Missed FSM Report
# ------------------------------------------------------------

def generate_missed_report( modules, missed_file):

    missed = []
    
    for path, data in modules:
    
        summary = data.get(
            "summary",
            {}
        )
    
        fsm = data.get(
            "fsm",
            {}
        )
    
        case_count = summary.get(
            "num_case_statements",
            0
        )
    
        state_count = len(
            fsm.get(
                "states",
                []
            )
        )
    
        #
        # Suspicious:
        # case statements exist
        # but FSM not extracted
        #
        if( case_count > 0 and state_count == 0 and summary.get("num_always_blocks",0) > 0):
   
            missed.append(
                get_module_name(
                    data,
                    path
                )
            )


    missed = sorted(set(missed))
    
    with open(
        missed_file,
        "w"
    ) as fp:
    
        fp.write(
            "POTENTIAL MISSED FSMS\n"
        )
    
        fp.write(
            "=" * 60 + "\n\n"
        )
    
        if not missed:
    
            fp.write(
                "No missed FSMs detected.\n"
            )
    
        else:
    
            for m in missed:
    
                fp.write(
                    m + "\n"
                )

# ------------------------------------------------------------
# Generate low confidence report
# ------------------------------------------------------------
def generate_low_confidence_report(
        rows,
        report_file):

    with open(
        report_file,
        "w"
    ) as fp:

        fp.write(
            "LOW CONFIDENCE FSMS\n"
        )

        fp.write(
            "=" * 60 + "\n\n"
        )

        found = False

        for row in rows:

            if row["confidence"] != "low":
                continue

            if is_non_fsm_module(
                row["module"]
            ):
                continue

            found = True

            fp.write(
                f"{row['module']}\n"
            )

        if not found:

            fp.write(
                "None\n"
            )

# ------------------------------------------------------------
# Training Candidate Report
# ------------------------------------------------------------
def generate_training_candidates(
        rows,
        report_file):

    with open(
        report_file,
        "w"
    ) as fp:

        fp.write(
            "FSM TRAINING CANDIDATES\n"
        )

        fp.write(
            "=" * 60 + "\n\n"
        )

        for row in rows:

            if (
                row["confidence"] == "high"
                and
                row["num_states"] >= 3
                and
                row["num_transitions"] >= 3
            ):

                fp.write(
                    f"{row['module']},"
                    f"{row['num_states']},"
                    f"{row['num_transitions']}\n"
                )

# ------------------------------------------------------------
# Largest FSM Report
# ------------------------------------------------------------

def generate_top_fsm_report(
        rows,
        report_file):

    fsms = [
        r
        for r in rows
        if (
            r["state_reg"]
            and
            r["num_states"] > 0
        )
    ]

    fsms.sort(
        key=lambda r:
            r["num_states"],
        reverse=True
    )

    with open(
        report_file,
        "w"
    ) as fp:

        fp.write(
            "TOP FSMS\n"
        )

        fp.write(
            "=" * 60 + "\n\n"
        )

        for row in fsms[:20]:

            fp.write(
                f"{row['module']:40s},"
                f"{row['style']},"
                f"{row['num_states']:4d},"
                f"{row['num_transitions']:4d}\n"
            )
# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

def main():

    if len(sys.argv) != 3:
    
        print(
            "Usage:\n"
            "  python fsm_report.py "
            "<out_dir> "
            "<report_dir>"
        )
    
        sys.exit(1)
    
    out_dir = sys.argv[1]
    report_dir = sys.argv[2]
    
    os.makedirs(
        report_dir,
        exist_ok=True
    )
    
    modules = collect_modules(
        out_dir
    )
    
    report_csv = os.path.join(
        report_dir,
        "fsm_report.csv"
    )
    
    summary_txt = os.path.join(
        report_dir,
        "fsm_summary.txt"
    )
    
    missed_txt = os.path.join(
        report_dir,
        "fsm_missed.txt"
    )

    low_conf_txt = os.path.join(
        report_dir,
        "fsm_low_confidence.txt"
    )

    training_txt = os.path.join(
        report_dir,
        "fsm_training_candidates.txt"
    )

    top_fsm_txt = os.path.join(
        report_dir,
        "fsm_top20.txt"
    )
    
    rows = generate_fsm_report(
        modules,
        report_csv
    )
    
    generate_summary(
        rows,
        summary_txt
    )
    
    generate_missed_report(
        modules,
        missed_txt
    )

    generate_low_confidence_report(
        rows,
        low_conf_txt
    )

    generate_training_candidates(
        rows,
        training_txt
    )

    generate_top_fsm_report(
        rows,
        top_fsm_txt
    )
    
    print( f"[INFO] Generated: {report_csv}")
    print( f"[INFO] Generated: {summary_txt}")
    print( f"[INFO] Generated: {missed_txt}")
    print( f"[INFO] Generated: {low_conf_txt}")
    print( f"[INFO] Generated: {training_txt}")
    print( f"[INFO] Generated: {top_fsm_txt}")

if __name__ == "__main__":
    main()
