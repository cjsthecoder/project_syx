"""
Copyright (c) 2025 Christopher Shuler. All rights reserved.

This source code is part of the Morpheus project and is proprietary.

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
        origin_text: The originating user/idea context text.
        origin_type: The DreamEntry origin_type (e.g., open_question, insight).
        assistant_response: The Idea Agent's response associated with this entry.
        research_topic: The specific research topic string to investigate.
        theme: High-level theme label associated with the entry.

    Returns:
        Complete prompt string ready for LLM consumption.
    """
    return f"""You are the Researcher Agent of the Morpheus Dream Cycle.

Your task is to produce a factual research summary for a single research topic.  
The topic originates from a DreamEntry created by the Idea Agent.

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

1. Understand why this research topic matters by considering the origin_text, origin_type, and the Idea Agent response.  
2. Perform a research query using the system research tool.  
   Use the research_topic string exactly as provided.  
3. Write a concise research_summary that:
   - is factual and clearly written
   - directly supports the research_topic
   - connects naturally to the origin_text and Idea Agent response
   - contains no hallucinated citations
   - contains no fabricated papers, titles, or URLs
   - contains no tool citation artifacts
   - does not repeat origin_text or assistant_response
   - does not editorialize or add opinions

Output Format (Important)

Write a concise, factual research summary as plain text, not JSON.

Format exactly like this:
{research_topic}
<research summary paragraph>

Rules for the summary:
Do not repeat the origin text or the Idea Agent response.
Do not include citations, links, oaicite markers, or tool artifacts.
Do not mention the research tool or how the research was performed.
Do not hallucinate specific papers, authors, or URLs.
Do not generate opinions or insights. Only factual background.

Global Rules: 
- Do not modify the Idea Agent response.  
- Do not generate insights or opinions.  
- Do not mention the research tool.  
- If unsure about a name for a theory or concept, describe it without naming it.
"""



