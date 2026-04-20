"""
Copyright (c) 2025 Syx Project Contributors. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
def build_project_summary_prompt(rag_context: str) -> str:
    return f"""You are a concise summarizer. Using only the context below, write a brief project context summary.
Keep it factual, avoid repetition, and focus on the most important persistent details that future Dream agents should know.
Target length: at most 300 words. Do not exceed this length cap. Do not include extra headers.

Context:
{rag_context}

Summary:"""



