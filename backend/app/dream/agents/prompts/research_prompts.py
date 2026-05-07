"""
Copyright (c) 2025 Syx Project Contributors. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
def build_research_prompt(
    project_summary_text: str,
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

1. Understand why this research topic matters by considering the project context, origin_text, origin_type, and Idea Agent response.
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



