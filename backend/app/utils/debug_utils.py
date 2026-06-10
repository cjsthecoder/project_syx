"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Debug file writing utilities for memory pipelines.

This module writes optional debug files under a project's memory directory when
the GENERATE_DEBUG_FILES setting is enabled.
"""
import logging
import os

from ..core.config import get_settings

logger = logging.getLogger(__name__)


def write_debug_file(project_id: str, filename: str, content: str) -> None:
    """
    Write a debug file under memory/{project_id}/debug/ when GENERATE_DEBUG_FILES is enabled.

    Args:
        project_id: Project identifier
        filename: Debug filename relative to the debug directory
        content: File contents to write
    """
    settings = get_settings()
    if not getattr(settings, "generate_debug_files", False):
        return

    try:
        base_dir = os.path.join(settings.memory_root, project_id, "debug")
        debug_path = os.path.join(base_dir, filename)
        os.makedirs(os.path.dirname(debug_path), exist_ok=True)
        with open(debug_path, "w", encoding="utf-8", newline="\n") as dbg:
            dbg.write(content)
        logger.debug("Wrote debug file to %s", debug_path)
    except Exception as de:
        logger.warning("Failed writing debug file %s for project=%s: %s", filename, project_id, de)
