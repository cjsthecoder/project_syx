"""



Copyright (c) 2025 Christopher Shuler. All rights reserved.

This source code is part of the Morpheus project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.

"""

from typing import Optional


def build_answer_question_prompt_local(question: str, topic: str, local_context: str) -> str:
    return f"""You are an assistant that answers a single question using only the information provided below.
Your task is to write a direct and helpful answer.
Do not invent facts that are not present in the supplied material.
If the memory does not give enough information, say so clearly.

Question:
{question}

Topic:
{topic}

Local Project Memory:
{local_context}

Answer requirements:
1. Return a single JSON object.
2. The JSON object must contain exactly one required field:
   "answer": "<string>"
3. Optional fields are allowed:
   "citations": []
   "notes": ""
   "confidence": 0.0
4. The answer must be a helpful paragraph that uses the provided memory only.

Return only the JSON object.
"""


def build_answer_question_prompt_remote(question: str, topic: str, local_context: str, remote_context: str) -> str:
    return f"""You are an assistant that answers a single question using only the information provided below.
Your task is to write a direct and helpful answer.
Do not invent facts that are not present in the supplied material.
If the combined memory and research do not give enough information, say so clearly.

Question:
{question}

Topic:
{topic}

Local Project Memory:
{local_context}

Remote Research:
{remote_context}

Answer requirements:
1. Return a single JSON object.
2. The JSON object must contain exactly one required field:
   "answer": "<string>"
3. Optional fields are allowed:
   "citations": []
   "notes": ""
   "confidence": 0.0
4. The answer must be a helpful paragraph that uses both memory and research only.

Return only the JSON object.
"""


def build_project_summary_prompt(rag_context: str) -> str:
    return f"""You are a concise summarizer. Using only the context below, write a brief project context summary.
Keep it factual, avoid repetition, and focus on the most important persistent details that future Dream agents should know.
Target length: approximately 400 words. Do not exceed this length cap. Do not include extra headers.

Context:
{rag_context}

Summary:"""

