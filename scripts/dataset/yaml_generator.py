#!/usr/bin/env python3
# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : yaml_generator.py
# Description : Yaml Generator implementation
#
# Component   : Kritva Forge
# Module      : dataset
# Layer       : Dataset
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
#     Purpose     : Convert module database into training artifacts.
#                   hierarchy learning
#                   SoC integration
#                   top-level reconstruction
#                  
# =============================================================================

import os
import re
import yaml
import shutil

from scripts.core.identity import IDENTITY_VERSION
from scripts.core.paths import find_absolute_paths


INCLUDE_COMMON_MODULES = True
# --------------------------------------------------
# MODULE YAML
# --------------------------------------------------

# --------------------------------------------------
# SEMANTIC TYPE SERIALIZATION
# --------------------------------------------------

def _semantic_type_info(symbol):
    """Return TypeInfo attached by semantic type enrichment."""
    if symbol is None:
        return None

    metadata = getattr(symbol, "metadata", None)
    if not isinstance(metadata, dict):
        return None

    return metadata.get("type_info")


def _width_to_yaml(width_info):
    """Convert semantic WidthInfo into plain YAML data."""
    if width_info is None:
        return None

    width = getattr(width_info, "width", None)
    msb = getattr(width_info, "msb", None)
    lsb = getattr(width_info, "lsb", None)
    kind = getattr(width_info, "kind", None)
    expression = getattr(width_info, "expression", None)

    if (
        width is None
        and msb is None
        and lsb is None
        and kind in (None, "unknown")
        and expression is None
    ):
        return None

    result = {}

    if kind is not None:
        result["kind"] = kind

    if msb is not None:
        result["msb"] = msb

    if lsb is not None:
        result["lsb"] = lsb

    if width is not None:
        result["width"] = width

    if expression is not None:
        result["expression"] = expression

    return result


def _clean_type_text(value):
    """Remove source comments and normalize whitespace in a type string."""
    if not isinstance(value, str):
        return value

    cleaned = re.sub(r"/\*.*?\*/", " ", value, flags=re.DOTALL)
    cleaned = re.sub(r"//[^\r\n]*", " ", cleaned)
    cleaned = " ".join(cleaned.split())
    return cleaned or None


def _apply_semantic_type(entry, symbol):
    """
    Overlay semantic TypeInfo onto one parser declaration.

    Parser fields are retained when semantic enrichment does not provide
    a corresponding value. The original parser type is preserved as
    ``raw_type`` when semantic TypeInfo is available.
    """
    original_type = entry.get("type")
    type_info = _semantic_type_info(symbol)
    if type_info is None:
        cleaned_type = _clean_type_text(original_type)
        if cleaned_type != original_type and original_type:
            entry["raw_type"] = original_type
        if cleaned_type is not None:
            entry["type"] = cleaned_type
        return entry

    raw_type = getattr(type_info, "raw", None) or original_type
    base_type = getattr(type_info, "base_type", None)
    type_ref = getattr(type_info, "type_ref", None)
    signed = getattr(type_info, "signed", None)
    width_info = getattr(type_info, "width", None)

    cleaned_type = _clean_type_text(original_type)
    if base_type:
        entry["datatype"] = base_type
        entry["type"] = base_type
    elif cleaned_type is not None:
        entry["type"] = cleaned_type

    width = _width_to_yaml(width_info)
    if width is not None:
        entry["width"] = width

    if signed is not None:
        entry["signed"] = signed

    if type_ref:
        entry["type_ref"] = type_ref

    if raw_type:
        entry["raw_type"] = raw_type

    return entry


def _serialize_entries(entries, semantic_scope):
    """Serialize parser declarations with semantic TypeInfo when available."""
    serialized = []

    symbols = {}
    if semantic_scope is not None:
        symbols = getattr(
            semantic_scope,
            "symbols",
            {},
        )

    for item in entries or []:
        entry = dict(item)
        symbol = symbols.get(entry.get("name"))

        if symbol is not None:
            _apply_semantic_type(entry, symbol)

        serialized.append(entry)

    return serialized


def _serialize_interfaces(interfaces, semantic_scope):
    """Serialize module interfaces using semantic PORT type information."""
    return {
        direction: _serialize_entries(
            interfaces.get(direction, []),
            semantic_scope,
        )
        for direction in ("inputs", "outputs", "inouts")
    }


def _serialize_signals(signals, semantic_scope):
    """Serialize module signals using semantic SIGNAL type information."""
    return _serialize_entries(
        signals,
        semantic_scope,
    )


def build_module_yaml(
        modules,
        module_name,
        semantic_ctx=None):

    mod = modules[module_name]

    semantic_scope = None
    if semantic_ctx is not None:
        semantic_scope = getattr(
            semantic_ctx,
            "scopes",
            {},
        ).get(module_name)

    spec = {

        "module":
            mod["name"],

        "parser":
            mod.get("parser"),
        
        "parser_version":
            mod.get("parser_version"),

        # KF-DQ-003: version of the node_id / buffer identity model
        # (scripts/core/identity.py).
        "identity_version":
            IDENTITY_VERSION,
        
        "type":
            mod.get("type"),

        "source_file":
            mod.get(
                "source_file"
            ),

        "parameters":
            mod.get(
                "parameters",
                {}
            ),

        "interfaces":
            _serialize_interfaces(
                mod.get(
                    "interfaces",
                    {}
                ),
                semantic_scope,
            ),

        "signals":
            _serialize_signals(
                mod.get(
                    "signals",
                    []
                ),
                semantic_scope,
            ),

        "clock_signals":
            mod.get(
                "clock_signals",
                []
            ),

        "reset_signals":
            mod.get(
                "reset_signals",
                []
            ),

        "assigns":
            mod.get(
                "assigns",
                []
            ),

        "always_blocks":
            mod.get(
                "always_blocks",
                []
            ),

        "case_statements":
            mod.get(
                "case_statements",
                []
            ),

        "fsm":
            mod.get(
                "fsm",
                {}
            ),

        "instances":
            mod.get(
                "instances",
                []
            )
    }

    # ---------------------------
    # Extract always block type like
    #  always_ff or always_comb
    # ----------------------------

    num_always_ff = sum(
        1 for b in spec["always_blocks"]
        if b.get("type") == "always_ff"
    )
    
    num_always_comb = sum(
        1 for b in spec["always_blocks"]
        if b.get("type") == "always_comb"
    )
    
    num_always_latch = sum(
        1 for b in spec["always_blocks"]
        if b.get("type") == "always_latch"
    )


    spec["summary"] = {

        "num_inputs":
            len(
                spec["interfaces"].get(
                    "inputs",
                    []
                )
            ),

        "num_outputs":
            len(
                spec["interfaces"].get(
                    "outputs",
                    []
                )
            ),

        "num_signals":
            len(
                spec["signals"]
            ),

        "num_instances":
            len(
                spec["instances"]
            ),

        "num_assigns":
            len(
                spec["assigns"]
            ),

        "num_always_blocks":
            len(
                spec["always_blocks"]
            ),

        "num_always_ff": num_always_ff,
        "num_always_comb": num_always_comb,
        "num_always_latch": num_always_latch,


        "num_case_statements":
            len(
                spec["case_statements"]
            ),

        "num_fsm_states":
            len(
                spec["fsm"].get(
                    "states",
                    []
                )
            )
    }

    spec["summary"]["child_modules"] = sorted(
        set(
            inst["module"]
            for inst in spec["instances"]
        )
    )

    return spec


# --------------------------------------------------
# HIERARCHY YAML
# --------------------------------------------------

def build_hierarchy_yaml(
        modules,
        top):

    hierarchy = {

        "top":
            top,

        "hierarchy":
            {}
    }

    for mod_name in sorted(modules):
    
        mod = modules[mod_name]
    
        hierarchy["hierarchy"][
            mod_name
        ] = [
    
            {
                "instance":
                    inst["instance"],
    
                "module":
                    inst["module"]
            }
    
            for inst in mod.get(
                "instances",
                []
            )
        ]

    return hierarchy


# --------------------------------------------------
# PROMPT GENERATOR
# --------------------------------------------------

def generate_module_prompt(spec):

    prompt = []
    
    prompt.append(
        "Generate complete synthesizable " +
        "Verilog RTL matching the " +
        "specification below.\n" +
        "Preserve module interfaces, " +
        "hierarchy, and behavior."
    )

    prompt.append(
        f"\nModule:\n{spec['module']}"
    )
    prompt.append(
        f"\nIs Top Module:\n{spec.get('is_top', False)}"
    )
    
    if spec.get("parameters"):
        prompt.append( "\nParameters:\n" + yaml.safe_dump( spec.get("parameters", {}), sort_keys=False))
    if spec.get("interfaces"):
        prompt.append( "\nInterfaces:\n" + yaml.safe_dump( spec.get("interfaces", {}), sort_keys=False))
    if spec.get("signals"):
        prompt.append( "\nInternal Signals:\n" + yaml.safe_dump( spec.get("signals", []), sort_keys=False))
    if spec.get("clock_signals"):
        prompt.append( "\nClock Signals:\n" + yaml.safe_dump( spec.get("clock_signals", []), sort_keys=False))
    if spec.get("reset_signals"):
        prompt.append( "\nReset Signals:\n" + yaml.safe_dump( spec.get("reset_signals", []), sort_keys=False))
    if spec.get("assigns"):
        prompt.append( "\nAssign Statements:\n" + yaml.safe_dump( spec.get("assigns", []), sort_keys=False))
    if spec.get("always_blocks"):
        prompt.append( "\nAlways Blocks:\n" + yaml.safe_dump( spec.get("always_blocks", []), sort_keys=False))
    if spec.get("case_statements"):
        prompt.append( "\nCase Statements:\n" + yaml.safe_dump( spec.get("case_statements", []), sort_keys=False))

    fsm = spec.get(
        "fsm",
        {}
    )
    if fsm and (
        fsm.get("states")
        or fsm.get("transitions")
    ):
        prompt.append(
            "\nFSM:\n" +
            yaml.safe_dump(
                fsm,
                sort_keys=False
            )
        )

    if spec.get("instances"):
        prompt.append( "\nSubmodule Instances:\n" + yaml.safe_dump( spec.get("instances", []), sort_keys=False))


    prompt.append(
        "\nRequirements:\n"+
        "- Generate synthesizable Verilog RTL\n"+
        "- Preserve hierarchy\n"+
        "- Preserve interfaces\n"+
        "- Preserve sequential logic\n"+
        "- Preserve combinational logic\n"+
        "- Preserve described behavior\n"+
        "- No delays (#)\n"+
        "- No force/release\n"+
        "- End every module with endmodule\n"+
        "Return Verilog RTL only."
    )

    return "\n".join(prompt)


# --------------------------------------------------
# RTL COPY
# --------------------------------------------------

def copy_rtl_files(
        modules,
        out_dir):

    rtl_dir = os.path.join(
        out_dir,
        "rtl"
    )

    os.makedirs(
        rtl_dir,
        exist_ok=True
    )

    copied = set()

    for mod in modules.values():

        # Runtime absolute path (parser-provided); persisted source_file is
        # repository-relative (KF-DQ-002) and cannot be opened directly.
        src = mod.get("source_path") or mod.get("source_file", "")

        if not src:
            continue

        if src in copied:
            continue

        copied.add(src)

        shutil.copy2(
            src,
            os.path.join(
                rtl_dir,
                os.path.basename(src)
            )
        )
    return len(copied)

# --------------------------------------------------
# WRITE OUTPUTS
# --------------------------------------------------

def _dump_portable_yaml(data, path):
    """Write YAML, refusing absolute host paths in persisted provenance (KF-DQ-002)."""
    text = yaml.safe_dump(
        data,
        sort_keys=False,
        allow_unicode=True
    )
    _assert_portable(text, path)
    with open(path, "w") as f:
        f.write(text)


def _assert_portable(text, path):
    hits = find_absolute_paths(text)
    if hits:
        line_no, line = hits[0]
        raise ValueError(
            f"refusing to persist absolute host path in {path} "
            f"(line {line_no}: {line.strip()[:120]}); provenance must be "
            "repository-relative (KF-DQ-002)"
        )


def build_summary_yaml(
        ip_name,
        modules,
        top,
        yaml_count,
        prompt_count,
        rtl_count):

    parser = "unknown"

    if modules:

        parser = next(
            iter(
                modules.values()
            )
        ).get(
            "parser",
            "unknown"
        )


    return {

        "ip":
            ip_name,

        "top_module":
            top,

        "parser":
             parser,

        "num_discovered_modules":
            len(modules),

        "num_yaml_files":
            yaml_count,

        "num_prompt_files":
            prompt_count,

        "num_rtl_files":
            rtl_count,

        "modules":
            sorted(
                modules.keys()
            )
    }

def write_semantic_ir(ip_name, module_name, modules, is_top, out_root):
    """Write normalized/semantic_ir/v2/<ip>/<module>.json (Semantic IR v2, KF-DQ-008).

    ``out_root`` is the canonical ``normalized/ir`` root; the semantic tree is
    its sibling ``normalized/semantic_ir/v2``.  Raises if the module has no
    extracted semantic document (nothing is skipped silently).
    """
    import hashlib
    from importlib.metadata import PackageNotFoundError, version

    from scripts.core.provenance import module_id
    from scripts.semantic_ir import model as SM
    from scripts.semantic_ir.extractor import finalize

    mod = modules[module_name]
    doc = mod.get("_semantic")
    if doc is None:
        raise RuntimeError(
            f"no Semantic IR v2 extracted for {ip_name}/{module_name}"
        )
    if "generator" not in doc:
        siblings = {
            name: other.get("_semantic")
            for name, other in modules.items()
            if other.get("_semantic") is not None
        }
        source_path = mod.get("source_path") or mod.get("source_file")
        with open(source_path, "rb") as handle:
            source_sha = hashlib.sha256(handle.read()).hexdigest()
        try:
            parser_version = "pyslang " + version("pyslang")
        except PackageNotFoundError:
            parser_version = "pyslang unknown"
        finalize(
            doc,
            ip=ip_name,
            module_id=module_id(ip_name, module_name),
            source_path=mod["source_file"],
            source_sha256=source_sha,
            siblings=siblings,
            sibling_ids={name: module_id(ip_name, name) for name in siblings},
            is_top=is_top,
            parser_version=parser_version,
        )
    text = SM.dumps(doc)
    path = os.path.join(
        os.path.dirname(os.path.abspath(out_root)),
        *SM.OUTPUT_SUBDIR.split("/"),
        ip_name,
        f"{module_name}.json",
    )
    _assert_portable(text, path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


def write_ip_outputs(
        ip_name,
        modules,
        top,
        out_root,
        semantic_ctx=None,
        prompt_root=None,
    ):
    """Write normalized module IR and generated prompts.

    Module YAML/hierarchy artifacts stay under ``out_root``.  Prompts can be
    redirected to the private data repository's ``generated/prompts`` tree.
    ``prompt_root=None`` preserves the legacy co-located layout.
    """


    ip_out = os.path.join(
        out_root,
        ip_name
    )

    modules_dir = os.path.join(
        ip_out,
        "modules"
    )

    if prompt_root is None:
        prompts_dir = os.path.join(ip_out, "prompts")
    else:
        prompts_dir = os.path.join(prompt_root, ip_name)


    os.makedirs(
        modules_dir,
        exist_ok=True
    )

    os.makedirs(
        prompts_dir,
        exist_ok=True
    )

    #
    # hierarchy.yaml
    #

    hierarchy = build_hierarchy_yaml(
        modules,
        top
    )

    with open(
        os.path.join(
            ip_out,
            "hierarchy.yaml"
        ),
        "w"
    ) as f:

        yaml.safe_dump(
            hierarchy,
            f,
            sort_keys=False,
            allow_unicode=True
        )

    #
    # module YAMLs + prompts
    #

    yaml_count = 0
    prompt_count = 0

    for module_name in sorted(
            modules.keys()
    ):

        mod = modules[
            module_name
        ]

        src = mod.get(
            "source_file",
            ""
        )

        #
        # Skip common library modules
        #

        if not INCLUDE_COMMON_MODULES:
            if "common" in src.split(
                    os.sep):
                continue

        spec = build_module_yaml(
            modules,
            module_name,
            semantic_ctx=semantic_ctx,
        )
        spec["is_top"] = (
            module_name == top
        )

        #
        # YAML
        #

        yaml_file = os.path.join(
            modules_dir,
            f"{module_name}.yaml"
        )

        _dump_portable_yaml(
            spec,
            yaml_file
        )

        yaml_count += 1

        #
        # KF-DQ-008: Semantic IR v2 next to the (unchanged) v1 IR
        #
        write_semantic_ir(
            ip_name,
            module_name,
            modules,
            spec["is_top"],
            out_root,
        )

        #
        # Prompt
        #

        prompt = generate_module_prompt(
            spec
        )

        prompt_file = os.path.join(
            prompts_dir,
            f"{module_name}.generate.txt"
        )

        _assert_portable(
            prompt,
            prompt_file
        )

        with open(
            prompt_file,
            "w"
        ) as f:

            f.write(prompt)

        prompt_count += 1

    copied = copy_rtl_files(
        modules,
        ip_out
    )

    summary = build_summary_yaml(
        ip_name,
        modules,
        top,
        yaml_count,
        prompt_count,
        copied
    )
    
    with open(
        os.path.join(
            ip_out,
            "summary.yaml"
        ),
        "w"
    ) as f:
    
        yaml.safe_dump(
            summary,
            f,
            sort_keys=False,
            allow_unicode=True
        )

    print( f"[INFO] {ip_name}")
    print( f"        YAMLs   : {yaml_count}")
    print( f"        Prompts : {prompt_count}")
    print( f"        RTL     : {copied}")
