"""Locked vocabulary for cascade-img.

Versioned JSON files in ``versions/`` are the contract a parity tool checks
against. The runtime emit/snapshot functions live in
:mod:`cascade_img.signals` (the sibling module — Python's import system
resolves the module before the package). v0.1 is unlocked until the daemon
ships a green capture against it.
"""
