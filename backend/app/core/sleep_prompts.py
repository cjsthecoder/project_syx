import logging

logger = logging.getLogger(__name__)


def generate_pruning_prompt(content: str) -> str:
    logger.info("[SLEEP][PRUNE] Building pruning prompt")
    return f"""You are given a daily memory file with:
 - header lines that start with #
 - boundary tags that mark the window:
   === BEGIN DAILY MEMORY: MM/DD/YYYY ===
   ...
   === END DAILY MEMORY: MM/DD/YYYY ===
 - paired USER/ASSISTANT blocks:

#timestamp: MM-DD-YYYY_HH:MM:SS
#route: <namespace>
#keep: true|false

--- USER (data-message-author-role: user) ---
<prompt>

*** ASSISTANT (data-message-author-role: assistant) ***
<response>

Your task:
1. PRESERVE ALL HEADER LINES (those that start with #) exactly as they are.
1a. PRESERVE THE DAILY MEMORY BOUNDARY TAGS exactly as they are:
    lines that begin with "=== BEGIN DAILY MEMORY:" and "=== END DAILY MEMORY:" including dates and surrounding blank lines.
2. Remove chatty filler, greetings, and follow-up offers from assistant responses.
3. For each USER question, keep only the substantive answer in the assistant's response—do not repeat or echo the user's question.
4. Do not alter the user's original prompts.
5. Keep assistant responses that contain explanations, facts, or decisions.
6. Keep the timestamps.
7. If multiple Q&A can be summarized more tightly, you may combine them, without losing important facts or decisions.
8. PRESERVE ANY REFERENCES section if present at the end.

Return only the pruned content (headers + pruned USER/ASSISTANT blocks), no extra commentary.

Here is the daily memory content:
{content}
"""


def generate_formatting_prompt(content: str) -> str:
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
  === BEGIN DAILY MEMORY: MM/DD/YYYY ===
  === END DAILY MEMORY: MM/DD/YYYY ===

RULES:
1) PRESERVE all header lines ('#...') EXACTLY (no edits).
2) PRESERVE role markers EXACTLY:
   --- USER (data-message-author-role: user) ---
   *** ASSISTANT (data-message-author-role: assistant) ***
3) PRESERVE the DAILY MEMORY boundary tags if present. Ensure ordering:
   - The BEGIN tag must be the FIRST line of the entire output.
   - The END tag must be the FINAL line of the entire output.
   - Do NOT place any content after the END tag.
4) If the input contains only one of the two tags (BEGIN or END), DO NOT invent the missing tag; format the body and keep the present tag in its correct position.
5) Structure the body into topic sections:
   === TOPIC: Normalized Short Title ===
   Then immediately these metadata lines (one per line):
   - #topics: 3–5 keywords
   - #decisions:
   - #open_questions:
   - #user_context:
   After that, include the original USER/ASSISTANT blocks and headers verbatim under the topic (no rewording).

6) Appendices must appear BEFORE the END tag in this exact order:

[Decisions Log]
- One item per line prefixed with '- '

[Open Questions]
Return a single JSON object with this structure:

{{
  "questions": [
    {{
      "question": "<exact question text or inferred question>",
      "topic": "<topic title where the question originated>",
      "resolution": "<ignore | remind_user | answer_local | answer_remote>"
    }}
  ]
}}

Rules for JSON:
- Deduplicate questions.
- Group questions by their originating Topic block.
- Extract explicit user questions (those ending in '?').
- ALSO extract implicit open questions using these patterns:
  • Statements of uncertainty ("I'm not sure...", "We haven't decided...", "Needs more thought", "Not clear how...")
  • Unresolved design choices ("We could do X or Y", "Two options exist...", "We need to pick between...")
  • Pending tasks framed as decisions ("We still need a name for...", "We haven't solved...", "Next we must decide...")
  • Assistant-raised forks ("This depends on whether...", "We need to determine...", "A key open decision is...")

- For implicit questions, convert the statement into a natural question without changing meaning.
  Example:
    Input: "We haven't decided on the API shape yet."
    Question: "What should the API shape be?"

- Classify each question with a resolution type based on the entire daily memory:
  • "ignore" for questions that are rhetorical, obsolete, duplicates, or already fully answered.
    Questions classified as "ignore" MUST NOT be included in the returned JSON.
  • "remind_user" for questions requiring user preference or subjective decision.
  • "answer_local" for questions likely answerable using today's memory or existing project RAG.
  • "answer_remote" for factual, technical, or research-driven questions requiring external sources.

- If no open questions exist, return {{ "questions": [] }}.

- Return ONLY the JSON object exactly as shown with no additional explanations.

7) Return ONLY the formatted output. No explanations.

Here is the pruned content:
{content}
"""


