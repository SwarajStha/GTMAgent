# -*- coding: utf-8 -*-
"""Wrapper: pre-imports torch before any DLL search path changes."""
import torch  # noqa: F401 — must be first import to fix Windows DLL init order
import exports_ml_pipeline
exports_ml_pipeline.main()
