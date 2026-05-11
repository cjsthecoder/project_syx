"""
Copyright (c) 2025-2026 Christopher Shuler. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
"""
Tracking package for instrumentation and telemetry.
"""

from .base import Instrumentation, NoopInstrumentation  # noqa: F401
from .instrumentation import (  # noqa: F401
    RealInstrumentation,
    get_instrumentation,
    init_instrumentation,
)

