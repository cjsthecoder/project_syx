"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
Prompt builder for the Dream cycle Research Agent.

Provides build_research_prompt, which constructs a single-topic research
instruction prompt grounded in project context, local retrieval context, and
the originating idea entry.
"""
def build_research_prompt(
    project_summary_text: str,
    local_context_text: str,
    origin_text: str,
    origin_type: str,
    assistant_response: str,
    research_topic: str,
    theme: str,
) -> str:
    """
    Build the Research Agent prompt for a single research topic.

    Args:
        project_summary_text: Concise project context summary for grounding.
        local_context_text: Expanded local project memory retrieved for this research topic.
        origin_text: The originating user or idea context text.
        origin_type: The DreamEntry origin_type (e.g., Open Question, Insight).
        assistant_response: The Idea Agent response associated with this entry.
        research_topic: The specific research topic string to investigate.
        theme: High-level theme label associated with the entry.

    Returns:
        Complete prompt string ready for LLM consumption.
    """
    return f"""You are the Researcher Agent of the Syx Dream Cycle.

Your task is to produce a concise factual research summary for a single research topic.
The summary should be useful as durable technical background memory for future project reasoning.

Project Context Summary:
{project_summary_text}

Expanded Local Retrieval Context:
{local_context_text}

Origin Text:
{origin_text}

Origin Type:
{origin_type}

Idea Agent Response:
{assistant_response}

Research Topic:
{research_topic}

Theme:
{theme}

Instructions:

1. Understand why this research topic matters by considering the project context, expanded local retrieval context, origin_text, origin_type, and Idea Agent response.
2. Perform research using the system research tool.
   Use the research_topic string exactly as provided.
3. Write a concise research_summary that:
   - is factual and clearly written
   - directly supports the research_topic
   - prioritizes concrete findings, studied architectures, benchmarks, operational patterns, design tradeoffs, constraints, and evaluation methods
   - emphasizes facts that would be useful as durable background memory for future Syx reasoning
   - connects naturally to the project context without repeating origin_text or assistant_response
   - avoids generic exposition when more specific technical findings are available
   - summarizes the main competing approaches and tradeoffs briefly when the evidence is mixed
   - contains no hallucinated citations
   - contains no fabricated papers, titles, authors, or URLs
   - contains no tool citation artifacts
   - does not editorialize or add opinions
   - does not propose actions or recommendations

How to use project context and retrieved memory:
- Treat Project Context Summary, Origin Text, Origin Type, Idea Agent Response, Research Topic, and Theme as the frame for what facts will be useful to Syx.
- Treat Expanded Local Retrieval Context as supporting project memory, not as external evidence and not as a source of new research topics.
- The local retrieval context may contain partial chunks, duplicates, stale prior Dream outputs, adjacent material, or unrelated-but-similar snippets.
- Use local context to understand what Syx already knows, what analogy or architecture concern motivated the topic, and which distinctions would be valuable in future chats.
- Ignore local snippets that are off-topic, merely adjacent, too truncated to support a claim, or not relevant to the Research Topic.
- Do not let local memory replace research; use research to provide factual grounding and use local memory to choose emphasis.
- If research contradicts or complicates local assumptions, summarize the factual nuance without calling out the conflict as a process note.
- Do not broaden the topic just because related concepts appear in local retrieval context.

Output Format (Important)

Write a concise, factual research summary as Markdown, not JSON.

Format exactly like this:
## {research_topic}

### Key findings
- <bullet 1>
- <bullet 2>

### Conditions / assumptions
- <bullet>

### Limitations / risks
- <bullet>

Rules for the summary:
Do not repeat the origin text or the Idea Agent response.
Do not include citations, links, oaicite markers, or tool artifacts.
Do not mention the research tool or how the research was performed.
Do not hallucinate specific papers, authors, or URLs.
Do not generate opinions, recommendations, or speculative insights.
Do not write process text such as "I researched" or "this was investigated."
Write so a future agent can recover the main learned facts without rereading the full source material.
Keep section headers exactly as written above and keep bullet formatting.

Global Rules:
- Do not modify the Idea Agent response.
- Do not generate insights or opinions.
- Do not mention the research tool.
- If unsure about a standard name for a theory or concept, describe it without naming it.
"""



