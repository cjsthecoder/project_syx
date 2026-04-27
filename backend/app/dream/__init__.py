"""
Copyright (c) 2025 Syx Project Contributors. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
# Dream package: dream cycle, context builder, and LLM helpers.

from .dreams import dream, write_dream_output  # noqa: F401
from .auto_accept import auto_accept_dreams  # noqa: F401
from .llm import dream_llm_call  # noqa: F401
from .context import build_dream_context, _strip_open_questions_section  # noqa: F401


