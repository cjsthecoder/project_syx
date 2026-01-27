"""
Copyright (c) 2025 Christopher Shuler. All rights reserved.

This source code is part of the Morpheus project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
import logging

logger = logging.getLogger(__name__)


def generate_pruning_prompt(content: str) -> str:
    logger.info("[SLEEP][PRUNE] Building pruning prompt")
    return f"""You are pruning conversational memory during a sleep cycle.

Your task is to SELECT which DAILY PAIR blocks should be kept for further
long-term memory processing and which should be discarded.

INPUT CONTAINS:
- A single MEMORY CONTAINER wrapper, one of:
  === BEGIN DAILY MEMORY: MM/DD/YYYY ===
  === END DAILY MEMORY: MM/DD/YYYY ===
  OR
  === BEGIN DREAM MEMORY: MM/DD/YYYY ===
  === END DREAM MEMORY: MM/DD/YYYY ===

- Inside the memory container are one or more DAILY PAIR blocks delimited by:
  === BEGIN DAILY PAIR ===
  === END DAILY PAIR ===

Each DAILY PAIR may contain:
- Header metadata lines beginning with '#', including:
  #timestamp
  #route
  #keep
  #topics
  #intent
  #type
- A USER block and an ASSISTANT block

CORE RULES:

1) MEMORY CONTAINER PRESERVATION
- PRESERVE the BEGIN and END MEMORY wrapper lines EXACTLY as provided.
- Do NOT remove, rename, reorder, or invent memory container tags.
- The wrapper must remain the first and last content in the output.

2) DAILY PAIR ATOMICITY
- Treat each DAILY PAIR as an indivisible unit.
- NEVER split, merge, or partially remove a DAILY PAIR.
- NEVER move metadata between DAILY PAIR blocks.

3) METADATA PRESERVATION
- PRESERVE all existing metadata lines EXACTLY as written.
- Do NOT edit, reword, add, or remove metadata.
- Do NOT infer new topics, intents, or types.

4) KEEP RULES
- If a DAILY PAIR contains '#keep: true', it MUST be preserved.
- If '#keep: false', you MAY discard it if it meets discard criteria.

5) DISCARD CRITERIA (all must apply)
A DAILY PAIR may be discarded ONLY if:
- It is not marked keep:true
- It contains no durable technical, narrative, design, or project-relevant information
- It does not introduce or resolve an important idea, decision, explanation, or question
- It would not be useful if retrieved later in isolation

Examples of discardable content:
- Social chatter, acknowledgements, pleasantries
- Meta comments about the conversation itself
- Low-information follow-ups already covered elsewhere

6) PRESERVE CRITERIA (any one is sufficient)
A DAILY PAIR SHOULD be preserved if it:
- Introduces a new concept, explanation, or framing
- Develops story world, characters, or narrative mechanics
- Explains technical, scientific, or system behavior
- Raises or answers a meaningful question
- Contains information likely useful for future recall or synthesis

7) OUTPUT REQUIREMENTS
- Return ONLY the original MEMORY CONTAINER wrapper and the selected DAILY PAIR blocks.
- Preserve original ordering.
- Preserve all text, formatting, and metadata verbatim.
- Do NOT add commentary, explanations, or summaries.
- Do NOT invent or remove DAILY PAIR boundaries.

Here is the memory content to prune:
{content}
"""


def generate_formatting_prompt(content: str) -> str:
    logger.info("[SLEEP][FORMAT] Building formatting prompt")
    return f"""You are formatting a pruned memory file during a sleep cycle.
Follow this output contract EXACTLY.

INPUT CONTAINS:
- A single MEMORY CONTAINER wrapper:
  === BEGIN DAILY MEMORY: MM/DD/YYYY ===
  === END DAILY MEMORY: MM/DD/YYYY ===
  OR
  === BEGIN DREAM MEMORY: MM/DD/YYYY ===
  === END DREAM MEMORY: MM/DD/YYYY ===

- Inside the memory container are one or more DAILY PAIR blocks delimited by:
  === BEGIN DAILY PAIR ===
  === END DAILY PAIR ===

Each DAILY PAIR may contain:
- Header metadata lines beginning with '#', including:
  #timestamp: MM-DD-YYYY_HH:MM:SS
  #route: <namespace>
  #keep: true|false
  #topics: <keywords>
  #intent: <purpose>
  #type: <category>
- Paired role blocks:
  --- USER (data-message-author-role: user) ---
  <prompt>
  *** ASSISTANT (data-message-author-role: assistant) ***
  <response>

RULES:

1) MEMORY CONTAINER PRESERVATION
- PRESERVE the BEGIN and END MEMORY wrapper lines EXACTLY as provided.
- The BEGIN wrapper MUST be the FIRST line of the output.
- The END wrapper MUST be the FINAL line of the output.
- Do NOT place any content outside the wrapper.
- If only one wrapper tag is present in the input, preserve it in its correct position and do NOT invent the missing one.

2) DAILY PAIR ATOMICITY
- Treat each DAILY PAIR as an indivisible unit.
- NEVER split, merge, reorder, or partially remove a DAILY PAIR.
- NEVER move metadata or content across DAILY PAIR boundaries.

3) METADATA PRESERVATION
- PRESERVE all existing header metadata lines ('#...') EXACTLY as written.
- Do NOT edit, reword, reorder, add, or remove metadata.
- Do NOT infer or synthesize new metadata fields.

4) ROLE MARKER PRESERVATION
- PRESERVE role markers EXACTLY:
  --- USER (data-message-author-role: user) ---
  *** ASSISTANT (data-message-author-role: assistant) ***

5) TOPIC STRUCTURE
- Structure the body into topic sections by grouping one or more complete DAILY PAIR blocks.
- Each topic section MUST begin with:
  === TOPIC: Normalized Short Title ===

- The topic title MUST be derived from existing #topics metadata
  (for example, a concise human-readable phrase).
- Do NOT invent new topics or reinterpret meaning.

- Immediately after the TOPIC line, repeat the following metadata verbatim
  if present in the first DAILY PAIR of that section:
  - #topics
  - #intent
  - #type

- If a metadata field is missing, leave it absent rather than inventing it.

- Under each topic section, include the DAILY PAIR blocks verbatim,
  including their BEGIN/END DAILY PAIR markers.

6) APPENDICES
Appendices must appear BEFORE the END MEMORY wrapper, in this exact order:

[Decisions Log]
- One item per line prefixed with '- '
- Only include explicit decisions stated in the content.
- Do NOT infer or invent decisions.

[Open Questions]
Return a single JSON object with this structure:

{{
  "questions": [
    {{
      "question": "<exact or naturally rewritten question>",
      "topic": "<topic title where the question originated>",
      "resolution": "<ignore | remind_user | answer_local | answer_remote>"
    }}
  ]
}}

Rules for Open Questions:
- Deduplicate questions.
- Group by originating TOPIC.
- Extract explicit user questions (ending with '?').
- ALSO extract implicit open questions using these patterns:
  • Statements of uncertainty
  • Unresolved design choices
  • Pending decisions or tasks
  • Assistant-raised forks or dependencies

- Convert implicit statements into natural questions without changing meaning.
- Classification rules:
  • "ignore": rhetorical, obsolete, duplicates, or already fully answered
    (ignored questions MUST NOT appear in the JSON)
  • "remind_user": subjective or preference-based
  • "answer_local": answerable from existing memory or project RAG
  • "answer_remote": requires external research

- If no open questions exist, return {{ "questions": [] }}.
- Return ONLY the JSON object. No extra text.

7) OUTPUT REQUIREMENTS
- Return ONLY the formatted output.
- Do NOT include explanations or commentary.
- Do NOT add or remove content beyond the rules above.

Here is the pruned memory content:
{content}
"""


def generate_dream_formatting_prompt(content: str) -> str:
    logger.info("[SLEEP][FORMAT] Building formatting prompt")
    return f"""You are formatting a pruned daily memory. Follow this output contract EXACTLY.

INPUT MAY CONTAIN:
- Header lines beginning with '#':
  #timestamp: MM-DD-YYYY_HH:MM:SS
  #route: <namespace>
  #keep: true|false
- Paired blocks:
  --- USER (data-message-author-role: user) ---
  <prompt>
  *** ASSISTANT (data-message-author-role: assistant) ***
  <response>
- Boundary tags:
  === BEGIN DREAM MEMORY: MM/DD/YYYY ===
  === END DREAM MEMORY: MM/DD/YYYY ===

RULES:
1) PRESERVE all header lines ('#...') EXACTLY (no edits).
2) PRESERVE role markers EXACTLY:
   --- USER (data-message-author-role: user) ---
   *** ASSISTANT (data-message-author-role: assistant) ***
3) PRESERVE the MEMORY boundary tags exactly as provided. Ensure ordering:
   - The BEGIN tag must be the FIRST line of the entire output.
   - The END tag must be the FINAL line of the entire output.
   - Do NOT place any content after the END tag.
4) If the input contains only one of the two tags (BEGIN or END), DO NOT invent the missing tag; format the body and keep the present tag in its correct position.
5) Structure the body into topic sections:
   === TOPIC: Normalized Short Title ===
   Then immediately these metadata lines (one per line):
   - #topics: 3–5 keywords
   After that, include the original USER/ASSISTANT blocks and headers verbatim under the topic (no rewording).

6) Return ONLY the formatted output. No explanations.

Here is the pruned content:
{content}
"""
