"""
Copyright (c) 2025-2026 Syx Project Contributors

SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
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

Expanded Local Retrieval Context:
{local_context}

Use of retrieved context:
- The local context is automatically retrieved and may contain partial chunks, duplicates, older Dream outputs, or adjacent material.
- Use only snippets that directly help answer the Question and Topic.
- Ignore retrieved material that is off-topic, merely adjacent, or too truncated to support a claim.
- Do not summarize the retrieved context broadly; answer the specific question.

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

Expanded Local Retrieval Context:
{local_context}

Remote Research:
{remote_context}

Use of retrieved context and research:
- The local context is automatically retrieved and may contain partial chunks, duplicates, older Dream outputs, or adjacent material.
- Use Remote Research for external factual grounding.
- Use Expanded Local Retrieval Context for project-specific framing, prior conclusions, or Syx analogies when they directly help answer the Question and Topic.
- Ignore retrieved material that is off-topic, merely adjacent, or too truncated to support a claim.
- If local memory and remote research conflict, mention the uncertainty briefly instead of forcing a false certainty.
- Do not summarize all supplied material; answer the specific question.

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



