"""Repertoire domain: the piece library, its journal, and its recordings.

This is the successor to the Rust `piano-progress` app. It owns its tables in
the ecosystem database and never reads that app's file except during a one-time
import (see :mod:`app.repertoire.importer`).
"""

from .schema import REPERTOIRE_SCHEMA

__all__ = ["REPERTOIRE_SCHEMA"]
