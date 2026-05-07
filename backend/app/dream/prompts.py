"""
Copyright (c) 2025 Syx Project Contributors. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
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



