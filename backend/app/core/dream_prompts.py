"""
Copyright (c) 2025 Syx Project Contributors. All rights reserved.

This source code is part of the Morpheus project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""

# Backwards-compatible shim: re-export Dream prompt helpers from the new package.

from .dream.prompts import *  # noqa: F401,F403
