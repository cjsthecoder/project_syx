"""
Copyright (c) 2025-2026 Syx Project Contributors

SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
def build_project_summary_prompt(rag_context: str) -> str:
    return f"""You are a concise summarizer for the Syx Dream Cycle.
Using only the current sleep-cycle memory below, write a brief project/dream-cycle orientation summary.
Keep it factual, avoid repetition, and focus on the persistent project details, active themes, unresolved questions, and useful framing that future Dream agents should know before reading expanded RAG context.
Do not summarize every memory item. Prefer the most durable context that explains what this cycle is about and why it matters for future reasoning.
Target length: at most 300 words. Do not exceed this length cap. Do not include extra headers.

Current Sleep-Cycle Memory:
{rag_context}

Summary:"""



