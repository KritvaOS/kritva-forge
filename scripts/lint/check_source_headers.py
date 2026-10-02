#!/usr/bin/env python3
# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : check_source_headers.py
# Description : Validate Kritva Forge source-file headers
#
# Component   : Kritva Forge
# Module      : lint
# Layer       : Development Infrastructure
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================

from __future__ import annotations
import argparse, subprocess
from pathlib import Path
EXTENSIONS={'.c':'cpp','.cc':'cpp','.cpp':'cpp','.cxx':'cpp','.h':'cpp','.hh':'cpp','.hpp':'cpp','.hxx':'cpp','.py':'python','.sh':'shell','.bash':'shell','.v':'rtl','.sv':'rtl','.vh':'rtl','.svh':'rtl','.dts':'dts','.dtsi':'dts','.yaml':'yaml','.yml':'yaml'}
SKIP_DIRS={'.git','build','generated','vendor','external','__pycache__','.pytest_cache','.mypy_cache'}
SKIP_FILES={'requirements.txt'}
def root():return Path(__file__).resolve().parents[2]
def skip(p,r):
 rel=p.relative_to(r)
 return any(x in SKIP_DIRS for x in rel.parts) or p.name in SKIP_FILES or 'templates' in rel.parts
def tracked(r):
 try:
  x=subprocess.run(['git','-C',str(r),'ls-files','-z'],check=True,capture_output=True).stdout
  return [r/z.decode() for z in x.split(b'\0') if z]
 except (subprocess.CalledProcessError,FileNotFoundError):return []
def prefix(k):
 return (['//==============================================================================','// Copyright (c) 2026 KritvaOS','// SPDX-License-Identifier: Apache-2.0','//'] if k in {'cpp','rtl'} else ['# =============================================================================','# Copyright (c) 2026 KritvaOS','# SPDX-License-Identifier: Apache-2.0','#'])
def validate(p,r):
 if skip(p,r) or p.suffix.lower() not in EXTENSIONS:return []
 k=EXTENSIONS[p.suffix.lower()];ls=p.read_text(encoding='utf-8',errors='replace').splitlines();o=1 if ls and ls[0].startswith('#!') else 0;pr=prefix(k);e=[]
 if ls[o:o+len(pr)]!=pr:return ['missing or invalid KritvaOS header prefix']
 h='\n'.join(ls[o:o+20])
 for f in ('File        :','Description :','Component   :','Module      :','Layer       :','Author      :','Created     :'):
  if f not in h:e.append(f"missing field '{f}'")
 if 'Copyright (c) 2026 KritvaOS' not in h:e.append('invalid copyright')
 if 'SPDX-License-Identifier: Apache-2.0' not in h:e.append('invalid SPDX')
 if not any('Created     : 02-10-2026' in x for x in ls[o:o+20]):e.append('invalid Created date; expected DD-MM-YYYY')
 return e
def main():
 a=argparse.ArgumentParser();a.add_argument('--mode',choices=('tracked','all'),default='tracked');a.add_argument('--strict',action='store_true');q=a.parse_args();r=root();fs=tracked(r) if q.mode=='tracked' else list(r.rglob('*'));fs=fs or list(r.rglob('*'));bad=checked=0
 for p in sorted(x for x in fs if x.is_file() and not skip(x,r) and x.suffix.lower() in EXTENSIONS):
  checked+=1;es=validate(p,r)
  if es:bad+=1;print('FAIL:',p.relative_to(r));[print('  -',e) for e in es]
 print(f'Source header check: {"FAIL" if bad else "PASS"} ({bad} failures, {checked} checked)');return 1 if bad and q.strict else 0
if __name__=='__main__':raise SystemExit(main())
