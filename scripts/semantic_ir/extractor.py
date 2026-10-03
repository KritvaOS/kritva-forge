# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : extractor.py
# Description : pyslang syntax tree to Semantic IR v2 module documents (KF-DQ-008)
#
# Component   : Kritva Forge
# Module      : semantic_ir
# Layer       : Semantic Analysis
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Semantic IR v2 extraction.

``ModuleExtractor(source_identity, source_manager, source_file).extract(module)``
turns one ``ModuleDeclarationSyntax`` into a source-level semantic document
(no elaboration).  ``finalize()`` adds the IP context (module identity,
source hash, instance resolution, versions, the reference index, the
condition / case indexes and counts).

Rules:

* every module member, statement and expression is either represented or
  recorded as an ``opaque`` node *and* listed in ``unsupported`` - nothing is
  dropped silently (``coverage`` records the member accounting);
* identifier references are resolved through the lexical scope chain
  (module, generate blocks, named blocks, loops, subroutines); names that
  cannot be resolved stay ``unresolved`` with their text;
* processes are containers (kind from the keyword, the event list as written,
  the body); process roles and scheduling semantics belong to KF-DQ-009, and
  driver / dependency graphs to KF-DQ-010;
* identities: :func:`scripts.semantic_ir.model.semantic_id` over the KF-DQ-003
  node identity.
"""

from __future__ import annotations

import re

from scripts.core.identity import node_identity
from scripts.semantic_ir import model as M

try:                                                     # pragma: no cover - import guard
    import pyslang
    _SyntaxNode = pyslang.syntax.SyntaxNode
except Exception:                                        # pragma: no cover
    pyslang = None
    _SyntaxNode = ()


# -----------------------------------------------------------------------------
# small helpers
# -----------------------------------------------------------------------------

def _kind(node) -> str:
    return str(node.kind).split(".", 1)[-1]


def _nodes(seq):
    """Syntax nodes of a (separated) list, skipping separator tokens."""
    if seq is None:
        return []
    out = []
    try:
        for i in range(len(seq)):
            item = seq[i]
            if isinstance(item, _SyntaxNode):
                out.append(item)
    except TypeError:
        pass
    return out


def _tok(token) -> str:
    if token is None:
        return ""
    try:
        return token.valueText or ""
    except Exception:
        return ""


_COMMENT_RE = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)


def _text(node, limit: int | None = None) -> str:
    if node is None:
        return ""
    text = " ".join(_COMMENT_RE.sub(" ", str(node)).split())
    if limit and len(text) > limit:
        text = text[: limit - 3] + "..."
    return text


_PROCESS_KINDS = {
    "AlwaysBlock": "always", "AlwaysFFBlock": "always_ff", "AlwaysCombBlock": "always_comb",
    "AlwaysLatchBlock": "always_latch", "InitialBlock": "initial", "FinalBlock": "final",
}
_ASSIGN_OPS = {"AssignmentExpression": "blocking", "NonblockingAssignmentExpression": "nonblocking"}
_INT_TYPE_BITS = {"integer": 32, "int": 32, "shortint": 16, "longint": 64, "byte": 8, "time": 64}


# -----------------------------------------------------------------------------
# extractor
# -----------------------------------------------------------------------------

class ModuleExtractor:
    """Extract one module.  ``source_identity`` is a KF-DQ-003 ``SourceIdentity``."""

    def __init__(self, source_identity, source_manager, source_file: str, unit_members=None):
        self.si = source_identity
        self.sm = source_manager
        self.source_file = source_file
        self.ids = set()
        # compilation-unit members of the same syntax tree (outside any module):
        # parameters, typedefs and enum members brought in by `include files
        self.unit_members = [m for m in (unit_members or []) if _kind(m) != "ModuleDeclaration"]

    # ------------------------------------------------------------------ ids/loc
    @staticmethod
    def _id_key(node):
        rng = node.sourceRange
        return (_kind(node), rng.start.offset, rng.end.offset)

    def _id(self, node, category: str, qualifier: str = "") -> str:
        try:
            rng = node.sourceRange
            start, end = self.si.location_key(rng.start), self.si.location_key(rng.end)
        except Exception:
            start = end = ""
        base = node_identity(self.source_file, _kind(node), start, end)
        sid = M.semantic_id(category, base, qualifier)
        n = 0
        while sid in self.ids:                    # same syntax node producing several objects
            n += 1
            sid = M.semantic_id(category, base, f"{qualifier}#{n}")
        self.ids.add(sid)
        return sid

    def _loc(self, node) -> dict:
        try:
            loc = node.sourceRange.start
            orig = self.sm.getFullyOriginalLoc(loc) if self.sm.isMacroLoc(loc) else loc
            return {
                "file": self.si.buffer_file(loc) or self.source_file,
                "line": int(self.sm.getLineNumber(orig)),
                "column": int(self.sm.getColumnNumber(orig)),
                "offset": int(orig.offset),
            }
        except Exception:
            return {"file": self.source_file, "line": 0, "column": 0, "offset": -1}

    # ------------------------------------------------------------------ scopes
    def _declare(self, name: str, ref_kind: str, target: str):
        if name:
            self.scopes[-1].setdefault(name, (ref_kind, target))

    def _lookup(self, name: str):
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        return None

    def _scope_path(self) -> str:
        return "/".join(self.scope_names)

    # ------------------------------------------------------------------ unsupported
    def _opaque(self, node, level: str, reason: str) -> dict:
        oid = self._id(node, f"opaque-{level}")
        rec = {"id": oid, "construct": _kind(node), "level": level, "reason": reason,
               "text": _text(node, 160), "loc": self._loc(node)}
        self.unsupported.append(rec)
        return rec

    # ==================================================================== module
    def extract(self, module) -> dict:
        self.ids = set()
        self.scopes = [{}]
        self.scope_names = []
        self.unsupported = []
        self.counters = {"members": 0, "represented": 0, "opaque": 0, "statements": 0,
                         "expressions": 0, "references": 0, "resolved_references": 0,
                         "external_references": 0}
        self._anon_enums = set()
        self.params, self.ports, self.signals, self.typedefs = [], [], [], []
        self.subroutines, self.assignments, self.processes = [], [], []
        self.instances, self.generates = [], []
        self.param_values = {}
        self.port_by_name = {}
        self._pending_init = []
        self._pending_sub = {}
        self._stmt_controls, self._stmt_reads = [], []
        self._cur_assign = []

        header = module.header
        name = _tok(header.name)
        mod_id = self._id(module, "module")

        # compilation-unit scope (outermost): declarations outside the module
        self.external = self._unit_scope()
        self.scopes.append({})

        # declarations first (module scope), so references resolve in any order
        for decl in _nodes(header.parameters.declarations if header.parameters else None):
            self._parameter_decl(decl, port_param=True)
        self._header_ports(header.ports)
        members = list(_nodes(module.members))
        self._predeclare(members)
        self._implicit_nets(members)
        for member in members:
            self._member(member, generate=None)

        doc = {
            "schema": {"name": M.SCHEMA_NAME, "version": M.SCHEMA_VERSION},
            "module": {"name": name, "id": mod_id, "loc": self._loc(module)},
            "extraction": "partial" if self.unsupported else "complete",
            "coverage": {"members": self.counters["members"],
                         "represented": self.counters["represented"],
                         "opaque": self.counters["opaque"]},
            "parameters": sorted(self.params, key=M.loc_key),
            "ports": self.ports,                                   # declaration order
            "signals": sorted(self.signals, key=M.loc_key),
            "typedefs": sorted(self.typedefs, key=M.loc_key),
            "subroutines": sorted(self.subroutines, key=M.loc_key),
            "assignments": sorted(self.assignments, key=M.loc_key),
            "processes": sorted(self.processes, key=M.loc_key),
            "instances": sorted(self.instances, key=M.loc_key),
            "generates": sorted(self.generates, key=M.loc_key),
            "unsupported": sorted(self.unsupported, key=M.loc_key),
            "external": self.external,
            "counts": {},
        }
        return doc

    # ------------------------------------------------------------------ compilation unit
    def _unit_scope(self) -> list:
        """Names declared outside the module in the same compilation unit (`include'd headers).

        They resolve as ``ref_kind: external`` (target ``null``); the declaration
        site is listed once in the document's ``external`` section.
        """
        out = {}

        def add(name, kind, node):
            if name and name not in out:
                out[name] = {"name": name, "kind": kind, "loc": self._loc(node)}
                self.scopes[0][name] = ("external", None)

        for m in self.unit_members:
            k = _kind(m)
            if k == "ParameterDeclarationStatement" and _kind(m.parameter) == "ParameterDeclaration":
                kw = _tok(m.parameter.keyword) or "parameter"
                for d in _nodes(m.parameter.declarators):
                    add(_tok(d.name), kw, d)
            elif k == "TypedefDeclaration":
                add(_tok(m.name), "typedef", m)
                if _kind(m.type) == "EnumType":
                    for d in _nodes(m.type.members):
                        add(_tok(d.name), "enum_member", d)
            elif k in ("FunctionDeclaration", "TaskDeclaration"):
                add(_text(m.prototype.name), "function" if k == "FunctionDeclaration" else "task", m)
        return sorted(out.values(), key=lambda r: (r["loc"]["file"], r["loc"]["line"], r["loc"]["column"],
                                                   r["name"]))

    # ------------------------------------------------------------------ declarations
    def _predeclare(self, members):
        """Register module-scope declarations (params, signals, typedefs, subroutines, genvars)."""
        for m in members:
            k = _kind(m)
            if k == "ParameterDeclarationStatement":
                self._parameter_decl(m.parameter, port_param=False, statement=m)
            elif k in ("DataDeclaration", "NetDeclaration"):
                self._data_decl(m)
            elif k == "PortDeclaration":
                self._port_decl(m)
            elif k == "TypedefDeclaration":
                self._typedef(m)
            elif k in ("FunctionDeclaration", "TaskDeclaration"):
                kind = "function" if k == "FunctionDeclaration" else "task"
                proto = m.prototype
                sname = _text(proto.name)
                sid = self._id(m, "subroutine")
                self._declare(sname, "subroutine", sid)
                self._pending_sub[self._id_key(m)] = (sid, sname, kind)
            elif k == "GenerateRegion":
                # a region without begin/end declares into the enclosing scope
                self._predeclare([x for x in _nodes(m.members)
                                  if _kind(x) not in ("LoopGenerate", "IfGenerate", "CaseGenerate", "GenerateBlock")])
            elif k == "GenvarDeclaration":
                for ident in _nodes(m.identifiers):
                    gname = _tok(ident.identifier)
                    gid = self._id(ident, "genvar")
                    self.params.append({"id": gid, "name": gname, "kind": "genvar", "type": "genvar", "signed": False, "packed": [], "width": None,
                                        "default": None, "value": None, "port_param": False,
                                        "scope": self._scope_path(), "loc": self._loc(ident)})
                    self._declare(gname, "genvar", gid)

    def _parameter_decl(self, decl, port_param: bool, statement=None):
        k = _kind(decl)
        if k != "ParameterDeclaration":
            self._opaque(decl, "member", f"parameter form {k} not modelled")
            return
        keyword = _tok(decl.keyword) or "parameter"
        ptype = _text(decl.type) or None
        info = self._type_info(decl.type)
        typed = info["type_kind"] != "implicit" or bool(info["packed"])
        for d in _nodes(decl.declarators):
            pname = _tok(d.name)
            pid = self._id(d, "parameter")
            default = self._expr(d.initializer.expr) if d.initializer else None
            value = self._const(default)
            if value is not None:
                self.param_values[pname] = value
            self.params.append({"id": pid, "name": pname, "kind": keyword, "type": ptype,
                                "signed": info["signed"], "packed": self._packed(info, pid),
                                "width": self._width(info) if typed else None,
                                "default": default, "value": value, "port_param": port_param,
                                "scope": self._scope_path(), "loc": self._loc(d)})
            self._declare(pname, "parameter", pid)

    def _type_info(self, tnode) -> dict:
        """kind/type/signed/packed for a data type syntax node."""
        if tnode is None:
            return {"type": None, "signed": False, "packed": [], "type_kind": "implicit"}
        k = _kind(tnode)
        signed = _tok(getattr(tnode, "signing", None)) == "signed"
        dims = [self._range(d) for d in _nodes(getattr(tnode, "dimensions", None))]
        if k == "ImplicitType":
            return {"type": None, "signed": signed, "packed": dims, "type_kind": "implicit"}
        if k in ("LogicType", "RegType", "BitType", "IntType", "IntegerType", "ShortIntType",
                 "LongIntType", "ByteType", "TimeType"):
            return {"type": _tok(tnode.keyword), "signed": signed, "packed": dims, "type_kind": "builtin"}
        if k == "NamedType":
            return {"type": _text(tnode.name), "signed": False, "packed": dims, "type_kind": "named"}
        if k == "EnumType":
            self._anonymous_enum(tnode)
            return {"type": "enum", "signed": signed, "packed": dims, "type_kind": "enum"}
        return {"type": _text(tnode, 120), "signed": signed, "packed": dims, "type_kind": k}

    def _range(self, dim) -> dict:
        spec = getattr(dim, "specifier", None)
        sel = getattr(spec, "selector", None) if spec is not None else None
        if sel is not None and _kind(sel) in ("SimpleRangeSelect", "AscendingRangeSelect", "DescendingRangeSelect"):
            left, right = self._expr(sel.left), self._expr(sel.right)
            return {"left": left, "right": right, "text": _text(dim),
                    "left_value": self._const(left), "right_value": self._const(right)}
        if sel is not None and _kind(sel) == "BitSelect":
            size = self._expr(sel.expr)
            return {"size": size, "text": _text(dim), "size_value": self._const(size)}
        return {"text": _text(dim), "opaque": True}

    @staticmethod
    def _width(info: dict) -> int | None:
        if info.get("type") in _INT_TYPE_BITS and not info["packed"]:
            return _INT_TYPE_BITS[info["type"]]
        if info["type_kind"] == "named":
            return None
        width = 1
        for r in info["packed"]:
            if r.get("left_value") is None or r.get("right_value") is None:
                return None
            width *= abs(r["left_value"] - r["right_value"]) + 1
        return width

    def _packed(self, info, owner: str) -> list:
        """The packed ranges of ``info`` for one declarator.

        One type (``wire [W-1:0] a, b;``) is shared by several declarators; the
        first gets the extracted ranges, later ones get copies whose reference
        identities are re-derived from (reference identity, declarator), so no
        identity is serialised twice.
        """
        info["_uses"] = info.get("_uses", 0) + 1
        if info["_uses"] == 1:
            return info["packed"]
        return self._clone(info["packed"], owner)

    def _clone(self, x, owner: str):
        if isinstance(x, dict):
            out = {k: (dict(v) if k == "loc" else self._clone(v, owner)) for k, v in x.items()}
            if x.get("op") == "ref":
                out["id"] = M.semantic_id("reference-copy", x["id"], owner)
            return out
        if isinstance(x, list):
            return [self._clone(v, owner) for v in x]
        return x

    def _decl_record(self, d, info, kind, extra=None, category="signal"):
        sid = self._id(d, category)
        unpacked = [self._range(x) for x in _nodes(d.dimensions)]
        rec = {"id": sid, "name": _tok(d.name), "kind": kind, "type": info["type"],
               "signed": info["signed"], "packed": self._packed(info, sid), "unpacked": unpacked,
               "width": self._width(info), "scope": self._scope_path(), "loc": self._loc(d)}
        if extra:
            rec.update(extra)
        return rec

    def _data_decl(self, m, local=False):
        k = _kind(m)
        if k == "NetDeclaration":
            info = self._type_info(m.type)
            kind, net_type = "net", _tok(m.netType)
        else:
            info = self._type_info(m.type)
            kind, net_type = "variable", None
        out = []
        for d in _nodes(m.declarators):
            name = _tok(d.name)
            if not local and not self.scope_names and name in self.port_by_name:
                # Verilog-95 "output q; reg q;" - the declaration types the port
                port = self.port_by_name[name]
                port.update({"kind": kind, "type": info["type"] or port["type"],
                             "signed": info["signed"] or port["signed"]})
                if info["packed"]:
                    port["packed"] = self._packed(info, port["id"])
                    port["width"] = self._width(info)
                port["declarations"] = port.get("declarations", []) + [self._loc(d)]
                if d.initializer:
                    self._pending_init.append((d, port["id"], kind))
                continue
            rec = self._decl_record(d, info, kind, {"net_type": net_type, "implicit": False,
                                                    "initializer": None}, "local" if local else "signal")
            self._declare(rec["name"], "local" if local else "signal", rec["id"])
            if d.initializer:
                self._pending_init.append((d, rec["id"], kind))
            if local:
                out.append(rec)
            else:
                self.signals.append(rec)
        return out

    # ------------------------------------------------------------------ ports
    def _header_ports(self, plist):
        self._pending_init = []
        if plist is None:
            return
        k = _kind(plist)
        if k == "AnsiPortList":
            prev = {"direction": "inout", "info": None, "kind": "net"}
            for p in _nodes(plist.ports):
                if _kind(p) != "ImplicitAnsiPort":
                    self._opaque(p, "member", f"port form {_kind(p)} not modelled")
                    continue
                hdr = p.header
                direction = _tok(getattr(hdr, "direction", None))
                hk = _kind(hdr)
                if hk == "VariablePortHeader":
                    info = self._type_info(hdr.dataType)
                    explicit = bool(direction) or info["type_kind"] != "implicit" or info["packed"]
                    if not explicit and prev["info"] is not None:      # inherits previous port
                        direction, info, pkind = prev["direction"], prev["info"], prev["kind"]
                    else:
                        direction = direction or prev["direction"]
                        pkind = "variable" if (info["type_kind"] != "implicit" or _tok(hdr.varKeyword)) else "net"
                elif hk == "NetPortHeader":
                    info = self._type_info(hdr.dataType)
                    direction, pkind = direction or prev["direction"], "net"
                else:
                    info = {"type": _text(hdr, 80), "signed": False, "packed": [], "type_kind": hk}
                    direction, pkind = direction or "unknown", "net"
                prev = {"direction": direction, "info": info, "kind": pkind}
                init = getattr(p.declarator, "initializer", None)
                rec = self._decl_record(p.declarator, info, pkind,
                                        {"direction": direction, "style": "ansi",
                                         "default": self._expr(init.expr) if init is not None else None}, "port")
                self.ports.append(rec)
                self.port_by_name[rec["name"]] = rec
                self._declare(rec["name"], "port", rec["id"])
        elif k == "NonAnsiPortList":
            for p in _nodes(plist.ports):
                ref = getattr(p, "expr", None)
                pname = _text(ref) if ref is not None else ""
                if _kind(p) != "ImplicitNonAnsiPort" or not re.fullmatch(r"[A-Za-z_][\w$]*", pname):
                    self._opaque(p, "member", f"port form {_kind(p)} not modelled")
                    continue
                rec = {"id": self._id(p, "port"), "name": pname, "kind": "net", "type": None,
                       "signed": False, "packed": [], "unpacked": [], "width": 1, "default": None,
                       "direction": "unknown", "style": "non-ansi", "scope": "", "loc": self._loc(p)}
                self.ports.append(rec)
                self.port_by_name[pname] = rec
                self._declare(pname, "port", rec["id"])
        else:
            self._opaque(plist, "member", f"port list {k} not modelled")

    def _port_decl(self, m):
        hdr = m.header
        direction = _tok(getattr(hdr, "direction", None)) or "unknown"
        info = self._type_info(getattr(hdr, "dataType", None))
        pkind = "net" if _kind(hdr) == "NetPortHeader" or info["type_kind"] == "implicit" else "variable"
        for d in _nodes(m.declarators):
            name = _tok(d.name)
            port = self.port_by_name.get(name)
            if port is None:
                # port declared but missing from the header list
                port = self._decl_record(d, info, pkind, {"direction": direction, "style": "non-ansi",
                                                          "default": None}, "port")
                self.ports.append(port)
                self.port_by_name[name] = port
                self._declare(name, "port", port["id"])
                continue
            port.update({"direction": direction, "kind": pkind, "type": info["type"],
                         "signed": info["signed"], "packed": self._packed(info, port["id"]),
                         "width": self._width(info), "declarations": [self._loc(d)]})

    # ------------------------------------------------------------------ typedef
    def _enum_members(self, t) -> list:
        members = []
        for d in _nodes(t.members):
            mid = self._id(d, "enum-member")
            val = self._expr(d.initializer.expr) if d.initializer else None
            if val is not None and self._const(val) is not None:
                self.param_values[_tok(d.name)] = self._const(val)
            members.append({"id": mid, "name": _tok(d.name), "value": val, "loc": self._loc(d)})
            self._declare(_tok(d.name), "enum_member", mid)
        return members

    def _anonymous_enum(self, t):
        """``enum {A, B} state;`` - members are recorded as an anonymous enum typedef."""
        key = self._id_key(t)
        if key in self._anon_enums:
            return
        self._anon_enums.add(key)
        base = getattr(t, "baseType", None)
        self.typedefs.append({"id": self._id(t, "typedef", "anonymous"), "name": None, "kind": "enum",
                              "base_type": self._type_info(base)["type"] if base is not None else None,
                              "members": self._enum_members(t), "text": _text(t, 200),
                              "scope": self._scope_path(), "loc": self._loc(t)})

    def _typedef(self, m):
        tname = _tok(m.name)
        tid = self._id(m, "typedef")
        t = m.type
        tk = _kind(t)
        members = []
        if tk == "EnumType":
            base = self._type_info(getattr(t, "baseType", None)) if getattr(t, "baseType", None) else None
            members = self._enum_members(t)
            kind, base_type = "enum", (base or {}).get("type")
        elif tk in ("StructType", "UnionType"):
            kind, base_type = ("union" if tk == "UnionType" else "struct"), None
            for mm in _nodes(getattr(t, "members", None)):
                for d in _nodes(getattr(mm, "declarators", None)):
                    members.append({"id": self._id(d, "struct-member"), "name": _tok(d.name),
                                    "type": _text(getattr(mm, "type", None), 80), "loc": self._loc(d)})
        else:
            kind, base_type = "alias", _text(t, 120)
        self.typedefs.append({"id": tid, "name": tname, "kind": kind, "base_type": base_type,
                              "members": members, "text": _text(m, 200), "scope": self._scope_path(),
                              "loc": self._loc(m)})
        self._declare(tname, "type", tid)

    # ------------------------------------------------------------------ implicit nets
    def _implicit_nets(self, members):
        """Undeclared identifiers driven by continuous assigns or used in port connections."""
        seen = []

        def roots(expr_node):
            k = _kind(expr_node)
            if k in ("IdentifierName",):
                return [expr_node]
            if k == "IdentifierSelectName":
                return [expr_node]
            if k == "ConcatenationExpression":
                out = []
                for e in _nodes(expr_node.expressions):
                    out += roots(e)
                return out
            if k in ("SimplePropertyExpr", "SimpleSequenceExpr"):
                return roots(expr_node.expr)
            return []

        def scan(nodes):
            for m in nodes:
                k = _kind(m)
                if k == "GenerateRegion":
                    scan([x for x in _nodes(m.members) if _kind(x) != "GenerateBlock"])
                if k == "ContinuousAssign":
                    for a in _nodes(m.assignments):
                        seen.extend(roots(a.left))
                elif k == "HierarchyInstantiation":
                    for inst in _nodes(m.instances):
                        for c in _nodes(inst.connections):
                            e = getattr(c, "expr", None)
                            if e is not None:
                                seen.extend(roots(e))

        scan(members)
        for node in seen:
            name = _tok(node.identifier)
            if name and self._lookup(name) is None:
                rec = {"id": self._id(node, "implicit-net"), "name": name, "kind": "net", "type": None,
                       "signed": False, "packed": [], "unpacked": [], "width": 1, "net_type": "wire",
                       "implicit": True, "initializer": None, "scope": "", "loc": self._loc(node)}
                self.signals.append(rec)
                self._declare(name, "signal", rec["id"])

    # ------------------------------------------------------------------ members
    def _member(self, m, generate):
        k = _kind(m)
        self.counters["members"] += 1
        handled = True
        if k in ("ParameterDeclarationStatement", "DataDeclaration", "NetDeclaration", "PortDeclaration",
                 "TypedefDeclaration", "GenvarDeclaration"):
            # declared by the scope pre-pass; emit pending declaration assignments
            self._flush_initializers(generate)
        elif k == "ContinuousAssign":
            for a in _nodes(m.assignments):
                self._assignment(a, "continuous", process=None, guards=[], generate=generate, node=a)
        elif k in _PROCESS_KINDS:
            self._process(m, generate)
        elif k == "HierarchyInstantiation":
            self._instantiation(m, generate)
        elif k in ("GenerateRegion", "LoopGenerate", "IfGenerate", "CaseGenerate", "GenerateBlock"):
            self._generate(m, generate)
        elif k in ("FunctionDeclaration", "TaskDeclaration"):
            self._subroutine(m)
        else:
            handled = False
        if handled:
            self.counters["represented"] += 1
        else:
            self.counters["opaque"] += 1
            self._opaque(m, "member", f"module member {k} not modelled")

    def _flush_initializers(self, generate):
        pending, self._pending_init = self._pending_init, []
        for d, target_id, kind in pending:
            value = self._expr(d.initializer.expr)
            reads = self._refs(value)
            aid = self._id(d, "assignment", "init")
            rk = "port" if any(p["id"] == target_id for p in self.ports) else "signal"
            target = {"op": "ref", "id": self._id(d, "reference", "init-target"), "name": _tok(d.name),
                      "loc": self._loc(d), "ref_kind": rk, "target": target_id}
            self.assignments.append({
                "id": aid, "kind": "declaration", "operator": "=", "target": target, "value": value,
                "writes": [target_id], "reads": reads, "guards": [], "process": None, "subroutine": None,
                "generate": generate, "unresolved_writes": [], "scope": self._scope_path(), "loc": self._loc(d),
            })
            for sig in self.signals + self.ports:
                if sig["id"] == target_id and "initializer" in sig:
                    sig["initializer"] = aid

    # ------------------------------------------------------------------ assignments
    def _assignment(self, a, kind, process, guards, generate, node, subroutine=None):
        k = _kind(a)
        if k in ("PostincrementExpression", "PreincrementExpression",
                 "PostdecrementExpression", "PredecrementExpression"):
            target = self._expr(a.operand)
            value = None                                       # x++ / x--: no separate value expression
            operator = _tok(a.operatorToken)
        else:
            target = self._expr(a.left)
            value = self._expr(a.right)
            operator = _tok(a.operatorToken)
        writes, index_reads, unresolved = self._lhs(target)
        reads = sorted(set(self._refs(value)) | set(index_reads))
        if operator not in ("=", "<="):
            reads = sorted(set(reads) | set(writes))           # compound: target is also read
        aid = self._id(node, "assignment")
        self.assignments.append({
            "id": aid, "kind": kind, "operator": operator, "target": target, "value": value,
            "writes": writes, "reads": reads, "guards": list(guards),
            "process": process, "subroutine": subroutine, "generate": generate,
            "unresolved_writes": unresolved, "scope": self._scope_path(), "loc": self._loc(node),
        })
        return aid, writes, reads

    def _lhs(self, target):
        """(written signal ids, ids read by index expressions, unresolved written names)."""
        writes, reads, unresolved = [], [], []

        def walk(e):
            op = e.get("op")
            if op == "ref":
                if e["target"] and e["ref_kind"] in ("port", "signal", "local"):
                    writes.append(e["target"])
                elif e["target"] is None:
                    unresolved.append(e["name"])
            elif op in ("index", "part_select", "member"):
                walk(e["base"])
                for key in ("index", "left", "right"):
                    if key in e and isinstance(e[key], dict):
                        reads.extend(self._refs(e[key]))
            elif op == "concat":
                for item in e["items"]:
                    walk(item)
        walk(target)
        return sorted(set(writes)), sorted(set(reads)), sorted(set(unresolved))

    def _refs(self, e) -> list:
        """Resolved signal/port/local ids referenced by an expression."""
        out = set()

        def walk(x):
            if isinstance(x, dict):
                if x.get("op") == "ref" and x.get("target") and x.get("ref_kind") in ("port", "signal", "local"):
                    out.add(x["target"])
                for v in x.values():
                    if isinstance(v, (dict, list)):
                        walk(v)
            elif isinstance(x, list):
                for v in x:
                    walk(v)
        if e is not None:
            walk(e)
        return sorted(out)

    # ------------------------------------------------------------------ processes
    def _process(self, m, generate):
        k = _kind(m)
        keyword = _tok(m.keyword)
        kind = _PROCESS_KINDS[k]
        pid = self._id(m, "process")
        events, implicit = [], kind in ("always_comb", "always_latch")
        stmt = m.statement
        body_node = stmt
        if _kind(stmt) == "TimingControlStatement" and _kind(stmt.timingControl) in (
                "EventControlWithExpression", "ImplicitEventControl", "EventControl", "RepeatedEventControl"):
            tc = stmt.timingControl
            if _kind(tc) == "ImplicitEventControl":
                implicit = True
            elif _kind(tc) == "EventControlWithExpression":
                events = self._events(tc.expr)
            elif _kind(tc) == "EventControl":
                events = [{"edge": "level", "expr": self._expr(tc.eventName)}]
            body_node = stmt.statement
        ctx = {"process": pid, "subroutine": None, "guards": [], "generate": generate}
        self._cur_assign = []
        self._stmt_controls, self._stmt_reads = [], []
        body = [self._stmt(body_node, ctx)] if body_node is not None else []
        assigns = self._cur_assign
        self._stmt_controls, self._stmt_reads = [], []
        sensitivity = "implicit" if implicit else ("list" if events else "none")
        self.processes.append({
            "id": pid, "kind": kind, "keyword": keyword, "sensitivity": sensitivity, "events": events,
            "body": body, "assignments": sorted(assigns), "generate": generate,
            "scope": self._scope_path(), "loc": self._loc(m),
        })

    def _events(self, ev) -> list:
        k = _kind(ev)
        if k == "ParenthesizedEventExpression":
            return self._events(ev.expr)
        if k == "BinaryEventExpression":
            return self._events(ev.left) + self._events(ev.right)
        if k == "SignalEventExpression":
            edge = _tok(ev.edge) or "level"
            if edge not in M.EDGES:
                edge = "level"
            expr = self._expr(ev.expr)
            return [{"edge": edge, "expr": expr}]
        return [{"edge": "level", "expr": self._expr(ev)}]

    # ------------------------------------------------------------------ statements
    def _stmt(self, s, ctx) -> dict:
        self.counters["statements"] += 1
        k = _kind(s)
        loc = self._loc(s)
        if k in ("SequentialBlockStatement", "ParallelBlockStatement"):
            bname = _tok(s.blockName.name) if s.blockName else None
            self.scopes.append({})
            body = []
            for item in _nodes(s.items):
                ik = _kind(item)
                if ik == "DataDeclaration":
                    for rec in self._data_decl(item, local=True):
                        did = rec["id"]
                        body.append({"stmt": "declaration", "id": self._id(item, "stmt-decl", did),
                                     "declaration": rec, "loc": rec["loc"]})
                    self._flush_local_inits(ctx)
                else:
                    body.append(self._stmt(item, ctx))
            self.scopes.pop()
            return {"stmt": "block", "id": self._id(s, "stmt"), "name": bname,
                    "parallel": k == "ParallelBlockStatement", "body": body, "loc": loc}
        if k == "ConditionalStatement":
            conds = _nodes(s.predicate.conditions)
            cond = self._expr(conds[0].expr) if conds else None
            if len(conds) != 1 or (conds and conds[0].matchesClause is not None):
                cond = self._opaque_expr(s.predicate, "pattern-matching / multi-condition predicate")
            sid = self._id(s, "stmt")
            then = self._stmt(s.statement, dict(ctx, guards=ctx["guards"] + [{"statement": sid, "branch": "then"}]))
            other = self._stmt(s.elseClause.clause,
                               dict(ctx, guards=ctx["guards"] + [{"statement": sid, "branch": "else"}])) \
                if s.elseClause else None
            return {"stmt": "if", "id": sid, "qualifier": _tok(s.uniqueOrPriority) or None,
                    "cond": cond, "then": then, "else": other, "loc": loc}
        if k == "CaseStatement":
            case_kind = _tok(s.caseKeyword)
            expr = self._expr(s.expr)
            items, default = [], None
            if _tok(s.matchesOrInside):
                return self._opaque_stmt(s, f"case ... {_tok(s.matchesOrInside)} not modelled")
            sid = self._id(s, "stmt")
            for it in _nodes(s.items):
                ik = _kind(it)
                if ik == "StandardCaseItem":
                    exprs = [self._expr(e) for e in _nodes(it.expressions)]
                    inner = dict(ctx, guards=ctx["guards"] + [{"statement": sid, "branch": "item",
                                                                 "item": len(items)}])
                    items.append({"exprs": exprs, "body": self._stmt(it.clause, inner), "loc": self._loc(it)})
                elif ik == "DefaultCaseItem":
                    inner = dict(ctx, guards=ctx["guards"] + [{"statement": sid, "branch": "default"}])
                    default = {"body": self._stmt(it.clause, inner), "loc": self._loc(it)}
                else:
                    items.append({"exprs": [], "body": self._opaque_stmt(it, f"case item {ik} not modelled"),
                                  "loc": self._loc(it)})
            return {"stmt": "case", "id": sid, "case_kind": case_kind,
                    "qualifier": _tok(s.uniqueOrPriority) or None, "expr": expr, "items": items,
                    "default": default, "loc": loc}
        if k == "ForLoopStatement":
            sid = self._id(s, "stmt")
            self.scopes.append({})
            init = []
            for item in _nodes(s.initializers):
                if _kind(item) == "ForVariableDeclaration":
                    d = item.declarator
                    info = self._type_info(item.type)
                    rec = self._decl_record(d, info, "variable", {"net_type": None, "implicit": False,
                                                                  "initializer": None}, "local")
                    self._declare(rec["name"], "local", rec["id"])
                    init.append({"declaration": rec,
                                 "value": self._expr(d.initializer.expr) if d.initializer else None})
                else:
                    aid, _, _ = self._assignment(item, "blocking", ctx["process"], ctx["guards"],
                                                 ctx["generate"], item, ctx["subroutine"])
                    self._cur_assign.append(aid)
                    init.append({"assignment": aid})
            stop = self._expr(s.stopExpr) if s.stopExpr else None
            self._stmt_controls.extend(self._refs(stop))
            steps = []
            for item in _nodes(s.steps):
                aid, _, _ = self._assignment(item, "compound" if "Assignment" not in _kind(item) or
                                             _tok(item.operatorToken) not in ("=",) else "blocking",
                                             ctx["process"], ctx["guards"], ctx["generate"], item,
                                             ctx["subroutine"])
                self._cur_assign.append(aid)
                steps.append(aid)
            body = self._stmt(s.statement, dict(ctx, guards=ctx["guards"] + [{"statement": sid, "branch": "body"}]))
            self.scopes.pop()
            return {"stmt": "loop", "id": sid, "loop_kind": "for", "init": init,
                    "cond": stop, "steps": steps, "body": body, "loc": loc}
        if k in ("LoopStatement", "ForeverStatement", "DoWhileStatement"):
            lk = {"ForeverStatement": "forever", "DoWhileStatement": "do_while"}.get(k) or _tok(s.repeatOrWhile)
            cond = self._expr(s.expr) if getattr(s, "expr", None) is not None else None
            sid = self._id(s, "stmt")
            body = self._stmt(s.statement, dict(ctx, guards=ctx["guards"] + [{"statement": sid, "branch": "body"}]))
            return {"stmt": "loop", "id": sid, "loop_kind": lk, "init": [], "cond": cond,
                    "steps": [], "body": body, "loc": loc}
        if k == "TimingControlStatement":
            control = _text(s.timingControl, 120)
            body = self._stmt(s.statement, ctx) if s.statement is not None else None
            return {"stmt": "timing", "id": self._id(s, "stmt"), "control": control, "body": body, "loc": loc}
        if k == "EmptyStatement":
            return {"stmt": "null", "id": self._id(s, "stmt"), "loc": loc}
        if k == "ReturnStatement":
            value = self._expr(s.returnValue) if getattr(s, "returnValue", None) is not None else None
            self._stmt_reads.extend(self._refs(value))
            return {"stmt": "return", "id": self._id(s, "stmt"), "value": value, "loc": loc}
        if k == "ExpressionStatement":
            e = s.expr
            ek = _kind(e)
            if ek in _ASSIGN_OPS or (ek.endswith("AssignmentExpression")) or ek in (
                    "PostincrementExpression", "PreincrementExpression",
                    "PostdecrementExpression", "PredecrementExpression"):
                akind = _ASSIGN_OPS.get(ek, "compound")
                aid, _, _ = self._assignment(e, akind, ctx["process"], ctx["guards"], ctx["generate"], s,
                                             ctx["subroutine"])
                self._cur_assign.append(aid)
                return {"stmt": "assign", "id": aid, "assignment": aid, "loc": loc}
            if ek in ("InvocationExpression", "SystemName"):
                expr = self._expr(e)
                self._stmt_reads.extend(self._refs(expr))
                return {"stmt": "call", "id": self._id(s, "stmt"), "expr": expr, "loc": loc}
            return self._opaque_stmt(s, f"expression statement {ek} not modelled")
        return self._opaque_stmt(s, f"statement {k} not modelled")

    def _flush_local_inits(self, ctx):
        pending, self._pending_init = self._pending_init, []
        for d, target_id, _ in pending:
            value = self._expr(d.initializer.expr)
            aid = self._id(d, "assignment", "local-init")
            self.assignments.append({
                "id": aid, "kind": "declaration", "operator": "=",
                "target": {"op": "ref", "id": self._id(d, "reference", "init-target"), "name": _tok(d.name),
                           "loc": self._loc(d), "ref_kind": "local", "target": target_id},
                "value": value, "writes": [target_id], "reads": self._refs(value), "guards": list(ctx["guards"]),
                "process": ctx["process"], "subroutine": ctx["subroutine"], "generate": ctx["generate"],
                "unresolved_writes": [], "scope": self._scope_path(), "loc": self._loc(d)})
            self._cur_assign.append(aid)

    def _opaque_stmt(self, s, reason) -> dict:
        rec = self._opaque(s, "statement", reason)
        return {"stmt": "opaque", "id": rec["id"], "construct": rec["construct"], "reason": reason,
                "loc": rec["loc"]}

    # ------------------------------------------------------------------ expressions
    def _opaque_expr(self, e, reason) -> dict:
        rec = self._opaque(e, "expression", reason)
        return {"op": "opaque", "id": rec["id"], "construct": rec["construct"], "text": rec["text"],
                "reason": reason}

    def _ref(self, name: str, node) -> dict:
        """A symbol use: its own identity and source span, the symbol, its kind and the defining entity."""
        hit = self._lookup(name)
        ref = {"op": "ref", "id": self._id(node, "reference", name), "name": name, "loc": self._loc(node)}
        if hit is None:
            ref.update(ref_kind="unresolved", target=None)
        elif hit[0] == "external":
            ref.update(ref_kind="external", target=None)
        else:
            ref.update(ref_kind=hit[0], target=hit[1])
        return ref

    def _expr(self, e) -> dict | None:
        if e is None:
            return None
        self.counters["expressions"] += 1
        k = _kind(e)
        if k == "ParenthesizedExpression":
            self.counters["expressions"] -= 1
            return self._expr(e.expression)
        if k in ("SimplePropertyExpr", "SimpleSequenceExpr"):
            self.counters["expressions"] -= 1
            return self._expr(e.expr)
        if k == "IdentifierName":
            return self._ref(_tok(e.identifier), e)
        if k == "IdentifierSelectName":
            base = self._ref(_tok(e.identifier), e)
            for sel in _nodes(e.selectors):
                base = self._select(base, sel)
            return base
        if k == "ElementSelectExpression":
            return self._select(self._expr(e.left), e.select)
        if k == "ScopedName":
            sep = _tok(e.separator)
            left = self._expr(e.left)
            right = _text(e.right)
            if sep == "." and left and left.get("op") == "ref" and left.get("ref_kind") in ("port", "signal", "local"):
                return {"op": "member", "base": left, "member": right}
            return {"op": "ref", "id": self._id(e, "reference", _text(e)), "name": _text(e), "loc": self._loc(e),
                    "ref_kind": "hierarchical" if sep == "." else "unresolved", "target": None}
        if k == "MemberAccessExpression":
            return {"op": "member", "base": self._expr(e.left), "member": _tok(e.name)}
        if k in ("IntegerLiteralExpression", "IntegerVectorExpression", "RealLiteralExpression",
                 "StringLiteralExpression", "UnbasedUnsizedLiteralExpression", "TimeLiteralExpression",
                 "NullLiteralExpression"):
            return self._literal(e, k)
        if k == "ConditionalExpression":
            conds = _nodes(e.predicate.conditions)
            cond = self._expr(conds[0].expr) if len(conds) == 1 else self._opaque_expr(e.predicate, "multi-condition")
            return {"op": "ternary", "cond": cond, "then": self._expr(e.left), "else": self._expr(e.right)}
        if k == "ConcatenationExpression":
            return {"op": "concat", "items": [self._expr(x) for x in _nodes(e.expressions)]}
        if k == "MultipleConcatenationExpression":
            inner = e.concatenation
            items = [self._expr(x) for x in _nodes(inner.expressions)] if _kind(inner) == "ConcatenationExpression" \
                else [self._expr(inner)]
            return {"op": "replicate", "count": self._expr(e.expression), "items": items}
        if k == "InvocationExpression":
            left = e.left
            lk = _kind(left)
            args = []
            if e.arguments is not None:
                for a in _nodes(e.arguments.parameters):
                    ak = _kind(a)
                    if ak == "OrderedArgument":
                        args.append(self._expr(a.expr))
                    elif ak == "NamedArgument":
                        args.append({"op": "binary", "operator": "=>",
                                     "left": {"op": "literal", "text": _tok(a.name), "value": None},
                                     "right": self._expr(a.expr) if a.expr else None})
                    elif ak == "EmptyArgument":
                        continue
                    else:
                        args.append(self._opaque_expr(a, f"argument {ak}"))
            if lk == "SystemName":
                return {"op": "call", "name": _tok(left.systemIdentifier), "system": True, "args": args,
                        "target": None}
            name = _text(left)
            hit = self._lookup(name)
            return {"op": "call", "name": name, "system": False, "args": args,
                    "target": hit[1] if hit and hit[0] == "subroutine" else None}
        if k == "SystemName":                       # $time, $stop without parentheses
            return {"op": "call", "name": _tok(e.systemIdentifier), "system": True, "args": [], "target": None}
        if k in ("CastExpression", "SignedCastExpression"):
            tnode = getattr(e, "left", None) if k == "CastExpression" else getattr(e, "signing", None)
            ttext = _text(tnode) if k == "CastExpression" else _tok(tnode)
            operand = self._expr(e.right if k == "CastExpression" else e.inner)
            return {"op": "cast", "type": ttext, "operand": operand}
        if type(e).__name__ == "PrefixUnaryExpressionSyntax" or type(e).__name__ == "PostfixUnaryExpressionSyntax":
            return {"op": "unary", "operator": _tok(e.operatorToken), "operand": self._expr(e.operand),
                    "postfix": type(e).__name__ == "PostfixUnaryExpressionSyntax"}
        if type(e).__name__ == "BinaryExpressionSyntax":
            # includes assignment operators used as expressions (e.g. generate step "g = g + 1")
            return {"op": "binary", "operator": _tok(e.operatorToken), "left": self._expr(e.left),
                    "right": self._expr(e.right)}
        return self._opaque_expr(e, f"expression {k} not modelled")

    def _select(self, base, sel) -> dict:
        s = sel.selector
        if s is None:
            return self._opaque_expr(sel, "empty selector")
        sk = _kind(s)
        if sk == "BitSelect":
            return {"op": "index", "base": base, "index": self._expr(s.expr)}
        if sk in ("SimpleRangeSelect", "AscendingRangeSelect", "DescendingRangeSelect"):
            mode = {"SimpleRangeSelect": ":", "AscendingRangeSelect": "+:", "DescendingRangeSelect": "-:"}[sk]
            return {"op": "part_select", "base": base, "mode": mode,
                    "left": self._expr(s.left), "right": self._expr(s.right)}
        return self._opaque_expr(sel, f"selector {sk} not modelled")

    def _literal(self, e, k) -> dict:
        text = _text(e)
        node = {"op": "literal", "text": text, "value": None}
        if k == "IntegerLiteralExpression":
            raw = text.replace("_", "")
            node["value"] = int(raw) if raw.isdigit() else None
        elif k == "IntegerVectorExpression":
            size = _tok(e.size)
            base = _tok(e.base).lower().lstrip("'").lstrip("s")
            digits = _tok(e.value).replace("_", "").lower()
            radix = {"b": 2, "o": 8, "d": 10, "h": 16}.get(base)
            node["base"] = base
            node["width"] = int(size) if size.isdigit() else None
            node["signed"] = "s" in _tok(e.base).lower()
            try:
                node["value"] = int(digits, radix) if radix else None
            except ValueError:
                node["value"] = None                    # x / z / ? digits
                node["has_xz"] = True
        elif k == "UnbasedUnsizedLiteralExpression":
            node["value"] = {"'0": 0, "'1": None}.get(text.lower())
            node["fill"] = text[-1:]
        return node

    # ------------------------------------------------------------------ constants
    def _const(self, e):
        if not isinstance(e, dict):
            return None
        op = e.get("op")
        try:
            if op == "literal":
                return e.get("value") if isinstance(e.get("value"), int) else None
            if op == "ref":
                return self.param_values.get(e["name"]) if e.get("ref_kind") == "parameter" else None
            if op == "unary":
                v = self._const(e["operand"])
                return None if v is None else {"-": -v, "+": v, "~": ~v, "!": int(not v)}.get(e["operator"])
            if op == "binary":
                a, b = self._const(e["left"]), self._const(e["right"])
                if a is None or b is None:
                    return None
                o = e["operator"]
                table = {"+": a + b, "-": a - b, "*": a * b, "&": a & b, "|": a | b, "^": a ^ b,
                         "<<": a << b if 0 <= b < 256 else None, ">>": a >> b if b >= 0 else None,
                         "==": int(a == b), "!=": int(a != b), "<": int(a < b), ">": int(a > b),
                         "<=": int(a <= b), ">=": int(a >= b)}
                if o in ("/", "%"):
                    return None if b == 0 else (a // b if o == "/" else a % b)
                if o == "**":
                    return a ** b if 0 <= b < 64 else None
                return table.get(o)
            if op == "ternary":
                c = self._const(e["cond"])
                return None if c is None else self._const(e["then"] if c else e["else"])
            if op == "call" and e.get("name") == "$clog2" and len(e["args"]) == 1:
                v = self._const(e["args"][0])
                return None if v is None or v < 0 else max(0, (v - 1).bit_length())
        except Exception:
            return None
        return None

    # ------------------------------------------------------------------ instances
    def _instantiation(self, m, generate):
        mtype = _tok(m.type)
        params = []
        if m.parameters is not None:
            for i, p in enumerate(_nodes(m.parameters.parameters)):
                pk = _kind(p)
                if pk == "OrderedParamAssignment":
                    params.append({"name": None, "position": i, "value": self._expr(p.expr)})
                elif pk == "NamedParamAssignment":
                    params.append({"name": _tok(p.name), "position": i,
                                   "value": self._expr(p.expr) if p.expr else None})
                else:
                    params.append({"name": None, "position": i, "value": self._opaque_expr(p, f"parameter {pk}")})
        for inst in _nodes(m.instances):
            iid = self._id(inst, "instance")
            conns = []
            for i, c in enumerate(_nodes(inst.connections)):
                ck = _kind(c)
                if ck == "NamedPortConnection":
                    expr = self._expr(c.expr) if c.expr is not None else None
                    kind = "named"
                    if expr is None and not _tok(c.openParen):
                        kind, expr = "implicit", self._ref(_tok(c.name), c)
                    conns.append({"port": _tok(c.name), "position": i, "kind": kind, "expr": expr})
                elif ck == "OrderedPortConnection":
                    conns.append({"port": None, "position": i, "kind": "ordered", "expr": self._expr(c.expr)})
                elif ck == "EmptyPortConnection":
                    conns.append({"port": None, "position": i, "kind": "empty", "expr": None})
                elif ck == "WildcardPortConnection":
                    conns.append({"port": "*", "position": i, "kind": "wildcard", "expr": None})
                else:
                    conns.append({"port": None, "position": i, "kind": "empty",
                                  "expr": self._opaque_expr(c, f"connection {ck}")})
            for c in conns:
                c["refs"] = self._refs(c["expr"])
                c["direction"] = "unknown"
            self.instances.append({
                "id": iid, "name": _tok(inst.decl.name) if inst.decl else None, "module": mtype,
                "parameters": params, "connections": conns,
                "dimensions": [self._range(d) for d in _nodes(inst.decl.dimensions)] if inst.decl else [],
                "target_module_id": None, "resolved": False, "generate": generate,
                "scope": self._scope_path(), "loc": self._loc(inst),
            })

    # ------------------------------------------------------------------ generate
    def _generate(self, g, parent):
        k = _kind(g)
        gid = self._id(g, "generate")
        rec = {"id": gid, "kind": {"GenerateRegion": "region", "LoopGenerate": "loop", "IfGenerate": "if",
                                   "CaseGenerate": "case", "GenerateBlock": "block"}[k],
               "parent": parent, "label": None, "representation": "source-level",
               "scope": self._scope_path(), "loc": self._loc(g)}
        self.generates.append(rec)
        if k == "GenerateRegion":
            inner = list(_nodes(g.members))
            for m in inner:
                self._member(m, gid)
        elif k == "LoopGenerate":
            gname = _tok(g.identifier)
            if _tok(g.genvar):
                gv = self._id(g, "genvar")
                self.params.append({"id": gv, "name": gname, "kind": "genvar", "type": "genvar", "signed": False, "packed": [], "width": None, "default": None,
                                    "value": None, "port_param": False, "scope": self._scope_path(),
                                    "loc": self._loc(g)})
                self._declare(gname, "genvar", gv)
            rec.update({"genvar": gname, "init": self._expr(g.initialExpr), "cond": self._expr(g.stopExpr),
                        "step": self._expr(g.iterationExpr)})
            self._member(g.block, gid)
        elif k == "IfGenerate":
            rec["cond"] = self._expr(g.condition)
            self._member(g.block, gid)
            if g.elseClause is not None:
                self._member(g.elseClause.clause, gid)
        elif k == "CaseGenerate":
            rec["cond"] = self._expr(g.condition)
            for it in _nodes(g.items):
                clause = getattr(it, "clause", None)
                if clause is not None:
                    self._member(clause, gid)
        elif k == "GenerateBlock":
            label = _tok(g.beginName.name) if g.beginName else (_tok(g.label.name) if g.label else None)
            rec["label"] = label
            self.scope_names.append(label or f"genblk@{rec['loc']['line']}")
            self.scopes.append({})
            inner = list(_nodes(g.members))
            self._predeclare_block(inner)
            for m in inner:
                self._member(m, gid)
            self.scopes.pop()
            self.scope_names.pop()

    def _predeclare_block(self, members):
        for m in members:
            k = _kind(m)
            if k == "ParameterDeclarationStatement":
                self._parameter_decl(m.parameter, port_param=False)
            elif k in ("DataDeclaration", "NetDeclaration"):
                self._data_decl(m)
            elif k == "TypedefDeclaration":
                self._typedef(m)
            elif k == "GenvarDeclaration":
                self._predeclare([m])
        self._implicit_nets(members)

    # ------------------------------------------------------------------ subroutines
    def _subroutine(self, m):
        pending = self._pending_sub.get(self._id_key(m))
        k = _kind(m)
        if pending is None:
            pending = (self._id(m, "subroutine"), _text(m.prototype.name), "function" if k == "FunctionDeclaration" else "task")
        sid, sname, kind = pending
        proto = m.prototype
        self.scopes.append({})
        self.scope_names.append(f"{kind}:{sname}")
        ports = []
        rtype = self._type_info(getattr(proto, "returnType", None)) if kind == "function" else None
        if kind == "function":
            rid = self._id(proto, "local", "return")
            ports.append({"id": rid, "name": sname, "kind": "variable", "direction": "return",
                          "type": (rtype or {}).get("type"), "signed": (rtype or {}).get("signed", False),
                          "packed": (rtype or {}).get("packed", []), "unpacked": [],
                          "width": self._width(rtype) if rtype else None, "scope": self._scope_path(),
                          "loc": self._loc(proto)})
            self._declare(sname, "local", rid)
        plist = getattr(proto, "portList", None)
        for p in _nodes(getattr(plist, "ports", None)):
            for d in [getattr(p, "declarator", None)]:
                if d is None:
                    continue
                info = self._type_info(getattr(p, "dataType", None))
                rec = self._decl_record(d, info, "variable", {"direction": _tok(getattr(p, "direction", None)) or "input"},
                                        "local")
                ports.append(rec)
                self._declare(rec["name"], "local", rec["id"])
        body = []
        ctx = {"process": None, "subroutine": sid, "guards": [], "generate": None}
        self._cur_assign = []
        saved_c, saved_r = self._stmt_controls, self._stmt_reads
        self._stmt_controls, self._stmt_reads = [], []
        for item in _nodes(m.items):
            ik = _kind(item)
            if ik == "PortDeclaration":
                info = self._type_info(getattr(item.header, "dataType", None))
                for d in _nodes(item.declarators):
                    rec = self._decl_record(d, info, "variable",
                                            {"direction": _tok(getattr(item.header, "direction", None)) or "input"},
                                            "local")
                    ports.append(rec)
                    self._declare(rec["name"], "local", rec["id"])
            elif ik == "DataDeclaration":
                for rec in self._data_decl(item, local=True):
                    body.append({"stmt": "declaration", "id": self._id(item, "stmt-decl", rec["id"]),
                                 "declaration": rec, "loc": rec["loc"]})
                self._flush_local_inits(ctx)
            else:
                body.append(self._stmt(item, ctx))
        self._stmt_controls, self._stmt_reads = saved_c, saved_r
        self.scopes.pop()
        self.scope_names.pop()
        self.subroutines.append({
            "id": sid, "name": sname, "kind": kind,
            "return_type": (rtype or {}).get("type") if rtype else None,
            "ports": ports, "body": body, "assignments": sorted(self._cur_assign),
            "scope": self._scope_path(), "loc": self._loc(m)})
        self._cur_assign = []


# -----------------------------------------------------------------------------
# finalize (IP context), versions, reference / condition / case indexes, counts
# -----------------------------------------------------------------------------

def finalize(doc: dict, *, ip: str, module_id: str, source_path: str, source_sha256: str,
             siblings: dict, sibling_ids: dict, is_top: bool, parser_version: str) -> dict:
    """Add IP context, resolve instances, versions, reference / condition / case indexes and counts."""
    doc["generator"] = {"extractor": M.EXTRACTOR, "parser": "pyslang", "parser_version": parser_version}
    doc["module"].update({"ip": ip, "module_id": module_id, "is_top": bool(is_top),
                          "source": {"path": source_path, "sha256": source_sha256}})

    # instances: resolve the child module within the IP and connection directions
    for inst in doc["instances"]:
        child = siblings.get(inst["module"])
        inst["target_module_id"] = sibling_ids.get(inst["module"])
        inst["resolved"] = inst["target_module_id"] is not None
        if child is None:
            continue
        ports = child["ports"]
        by_name = {p["name"]: p for p in ports}
        for c in inst["connections"]:
            port = by_name.get(c["port"]) if c["port"] not in (None, "*") else (
                ports[c["position"]] if c["kind"] == "ordered" and c["position"] < len(ports) else None)
            if port is not None:
                c["direction"] = port.get("direction") if port.get("direction") in M.DIRECTIONS else "unknown"
                if c["port"] is None:
                    c["port"] = port["name"]

    doc["versions"] = versions(parser_version)
    doc["references"] = build_references(doc)
    doc["conditions"], doc["cases"] = build_control(doc)
    doc["counts"] = count(doc)
    return doc


def versions(parser_version: str) -> dict:
    """Explicit schema / identity / parser / compatibility versions (criteria section 9)."""
    from scripts.core.identity import IDENTITY_VERSION

    return {
        "schema": M.SCHEMA_VERSION,
        "identity": M.IDENTITY_VERSION,
        "node_identity": IDENTITY_VERSION,
        "parser": parser_version,
        "compatibility": {"normalized_ir": M.COMPATIBLE_NORMALIZED_IR},
    }


# ---------------------------------------------------------------------------- tree walking

def _walk_owned(doc: dict):
    """Yield (owner id, usage, ref node) for every reference in the document.

    ``owner`` is the nearest enclosing semantic entity (assignment, statement,
    process, instance, parameter, port, signal, typedef, generate, subroutine).
    ``usage`` is ``write`` for the written base of an assignment target and
    ``read`` for every other use (including index expressions of a target).
    """
    out = []

    def expr(e, owner, usage="read"):
        if isinstance(e, dict):
            if e.get("op") == "ref":
                out.append((owner, usage, e))
                return
            if usage == "write" and e.get("op") in ("index", "part_select", "member"):
                expr(e.get("base"), owner, "write")
                for key in ("index", "left", "right"):
                    expr(e.get(key), owner, "read")
                return
            if usage == "write" and e.get("op") == "concat":
                for item in e.get("items", []):
                    expr(item, owner, "write")
                return
            for key, v in e.items():
                if key != "loc":
                    expr(v, owner, "read")
        elif isinstance(e, list):
            for v in e:
                expr(v, owner, usage)

    def stmt(st, owner):
        if not isinstance(st, dict):
            return
        sid = st.get("id", owner)
        kind = st.get("stmt")
        if kind == "if":
            expr(st.get("cond"), sid)
            stmt(st.get("then"), sid)
            stmt(st.get("else"), sid)
        elif kind == "case":
            expr(st.get("expr"), sid)
            for it in st.get("items", []):
                expr(it.get("exprs"), sid)
                stmt(it.get("body"), sid)
            if st.get("default"):
                stmt(st["default"].get("body"), sid)
        elif kind == "block":
            for x in st.get("body", []):
                stmt(x, sid)
        elif kind == "loop":
            for i in st.get("init", []):
                if "declaration" in i:
                    decl(i["declaration"])
                    expr(i.get("value"), i["declaration"]["id"])
            expr(st.get("cond"), sid)
            stmt(st.get("body"), sid)
        elif kind == "timing":
            stmt(st.get("body"), sid)
        elif kind in ("call", "return"):
            expr(st.get("expr") or st.get("value"), sid)
        elif kind == "declaration":
            decl(st["declaration"])

    def decl(d):
        for key in ("packed", "unpacked", "default"):
            expr(d.get(key), d["id"])

    for section in ("parameters", "ports", "signals"):
        for d in doc[section]:
            decl(d)
    for t in doc["typedefs"]:
        for m in t.get("members", []):
            expr(m.get("value"), m["id"])
    for a in doc["assignments"]:
        expr(a["target"], a["id"], "write")
        expr(a.get("value"), a["id"])
    for p in doc["processes"]:
        for ev in p.get("events", []):
            expr(ev.get("expr"), p["id"])
        for st in p["body"]:
            stmt(st, p["id"])
    for sub in doc["subroutines"]:
        for port in sub.get("ports", []):
            decl(port)
        for st in sub.get("body", []):
            stmt(st, sub["id"])
    for inst in doc["instances"]:
        expr(inst.get("parameters"), inst["id"])
        expr(inst.get("dimensions"), inst["id"])
        for c in inst.get("connections", []):
            expr(c.get("expr"), inst["id"], "connect")
    for g in doc["generates"]:
        expr({k: v for k, v in g.items() if k not in ("id", "loc")}, g["id"])
    return out


def build_references(doc: dict) -> list:
    """One record per symbol use (criteria section 6.9).

    Declarations live in their own sections (parameters, ports, signals, ...);
    every *use* of a symbol is listed here with its own identity, the
    referencing entity (``source``), the defining entity (``target``, or null
    when unresolved / external / hierarchical), the reference kind, the usage
    and the source span.  Sorted by (file, line, column, id).
    """
    refs = []
    for owner, usage, e in _walk_owned(doc):
        # the source span lives in the index only (the tree node keeps id / name / kind / target)
        refs.append({"id": e["id"], "symbol": e["name"], "ref_kind": e["ref_kind"], "target": e["target"],
                     "source": owner, "usage": usage, "loc": e.pop("loc")})
    return sorted(refs, key=M.loc_key)


def _ref_ids(e) -> list:
    out, stack = [], [e]
    while stack:
        x = stack.pop()
        if isinstance(x, dict):
            if x.get("op") == "ref":
                out.append(x["id"])
            else:
                stack.extend(v for k, v in x.items() if k != "loc")
        elif isinstance(x, list):
            stack.extend(x)
    return sorted(out)


def build_control(doc: dict) -> tuple[list, list]:
    """Flat indexes of conditional (if) and case statements (criteria sections 5 and 6.7).

    The statement trees inside processes / subroutines hold the expressions;
    each index record has the statement's identity, its owner (process or
    subroutine), the qualifier, the identities of the references used by the
    predicate / selector / labels and its branches (by statement id), so
    consumers need not walk the trees.  Expressions are not duplicated.
    """
    conditions, cases = [], []

    def sid(st):
        return st.get("id") if isinstance(st, dict) else None

    def visit(st, owner):
        if not isinstance(st, dict):
            return
        kind = st.get("stmt")
        if kind == "if":
            conditions.append({"id": st["id"], "owner": owner, "qualifier": st.get("qualifier"),
                               "predicate_references": _ref_ids(st.get("cond")),
                               "then": sid(st.get("then")), "else": sid(st.get("else")), "loc": st["loc"]})
            visit(st.get("then"), owner)
            visit(st.get("else"), owner)
        elif kind == "case":
            cases.append({"id": st["id"], "owner": owner, "case_kind": st["case_kind"],
                          "qualifier": st.get("qualifier"), "selector_references": _ref_ids(st.get("expr")),
                          "items": [{"labels": len(it.get("exprs", [])), "label_references": _ref_ids(it.get("exprs")),
                                     "body": sid(it.get("body")), "loc": it.get("loc")}
                                    for it in st.get("items", [])],
                          "default": None if not st.get("default") else
                          {"body": sid(st["default"].get("body")), "loc": st["default"].get("loc")},
                          "loc": st["loc"]})
            for it in st.get("items", []):
                visit(it.get("body"), owner)
            if st.get("default"):
                visit(st["default"].get("body"), owner)
        elif kind == "block":
            for x in st.get("body", []):
                visit(x, owner)
        elif kind in ("loop", "timing"):
            visit(st.get("body"), owner)

    for p in doc["processes"]:
        for st in p["body"]:
            visit(st, p["id"])
    for sub in doc["subroutines"]:
        for st in sub.get("body", []):
            visit(st, sub["id"])
    return sorted(conditions, key=M.loc_key), sorted(cases, key=M.loc_key)


def count(doc: dict) -> dict:
    refs = doc["references"]
    kinds = {}
    for r in refs:
        kinds[r["ref_kind"]] = kinds.get(r["ref_kind"], 0) + 1
    exprs = statements = 0
    stack = [doc[k] for k in ("parameters", "ports", "signals", "typedefs", "subroutines", "assignments",
                              "processes", "instances", "generates")]
    while stack:
        x = stack.pop()
        if isinstance(x, dict):
            if "op" in x:
                exprs += 1
            if "stmt" in x and x.get("stmt") != "declaration":
                statements += 1
            stack.extend(v for k, v in x.items() if k != "loc")
        elif isinstance(x, list):
            stack.extend(x)
    return {
        "parameters": len(doc["parameters"]), "ports": len(doc["ports"]), "signals": len(doc["signals"]),
        "typedefs": len(doc["typedefs"]), "subroutines": len(doc["subroutines"]),
        "assignments": len(doc["assignments"]), "processes": len(doc["processes"]),
        "instances": len(doc["instances"]), "generates": len(doc["generates"]),
        "conditions": len(doc["conditions"]), "cases": len(doc["cases"]),
        "statements": statements, "expressions": exprs,
        "references": len(refs),
        "resolved_references": sum(1 for r in refs if r["target"] is not None),
        "external_references": kinds.get("external", 0),
        "hierarchical_references": kinds.get("hierarchical", 0),
        "unresolved_references": kinds.get("unresolved", 0),
        "write_references": sum(1 for r in refs if r["usage"] == "write"),
        "external_declarations": len(doc.get("external", [])),
        "unresolved_instances": sum(1 for i in doc["instances"] if not i.get("resolved")),
        "unsupported": len(doc["unsupported"]),
    }
