# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : logging.py
# Description : Logging implementation
#
# Component   : Kritva Forge
# Module      : core
# Layer       : Core Infrastructure
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
import logging
import sys

LOG_FORMAT = (
    "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
)

def setup_logging(level=logging.INFO):
    logging.basicConfig(
        level=level,
        format=LOG_FORMAT,
        stream=sys.stdout,
    )
