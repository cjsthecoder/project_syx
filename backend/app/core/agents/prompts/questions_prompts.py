"""
Copyright (c) 2025 Syx Project Contributors. All rights reserved.

This source code is part of the Morpheus project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""


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

