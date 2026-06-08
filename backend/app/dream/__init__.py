"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Package initializer for the dream subpackage.

Re-exports the Dream cycle entry points, dream output writer, auto-accept
helper, and dream context builder.
"""
# Dream package: dream cycle, context builder, and debug helpers.

from .auto_accept import auto_accept_dreams  # noqa: F401
from .context import _strip_open_questions_section, build_dream_context  # noqa: F401
from .dreams import dream, write_dream_output  # noqa: F401
