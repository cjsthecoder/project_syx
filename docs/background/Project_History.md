# Project History

## Starting Point: A Neuroscience-Inspired Question

This idea originally came from the neuroscience podcast *Inner Cosmos with David Eagleman*, where he interviewed technologist and writer Kevin Kelly. They were discussing different aspects of AI and how alike or different it may be from human intelligence.

At one point they mentioned something about how AI will need to forget. I thought that was interesting, and my first thought was that AI may need to sleep like humans. During that time, memory processing could take place, including forgetting.

I had some high-level ideas. Nothing I thought would actually work at the time, but I felt it was interesting enough to write a few articles on LinkedIn about it.

## Early Writing and Design Notes

The first article was:

[Should Androids Dream](original_articles/Should_Androids_Dream.md)

Later I published:

[AI Short-Term Memory](original_articles/AI_Short_Term_Memory.md)

Followed by:

[Pruning the Data](original_articles/Pruning_The_Data.md)

At that point I still thought it was a cool idea, but probably something that would take a team of AI experts to build.

## From Idea to Proof of Concept

Over the following few months, I started to think there might be a way to build a proof of concept. It would be mostly manual, but it would let me save chats, clean them up, combine them into a larger file, and upload that file into an AI project as a RAG source.

## First Iterations

Over the next few months, there were three iterations of the proof of concept.

* Iteration 1: Tested whether I could extract a chat from HTML, format it into a useful text file, and upload it to RAG. Then I tested whether the AI project could use that chat history in a useful way. It turned out the answer was yes.

* Iteration 2: Experimented with summarizing the chats before uploading them. I did not think this worked well. Summarizing removed too much of the content. But this evolved into pruning the chats instead, removing extraneous wording like “Great idea...” at the beginning and “Would you like me to do one of these things next?” at the end. That worked. It cut down the size while maintaining the content.

* Iteration 3: Experimented with tagging the chat pairs with topic keywords to help semantic search find them more easily. This also worked, with the AI using past chats more readily than before.

## Realization That the Architecture Was Workable

It turned out that there were two things happening at once.

First, I had consolidated nearly every chat I had on this topic into the project. By the end of the proof of concept, that represented around nine months of chats. I would guess it was in the neighborhood of 1,000 turns, all on this one topic.

Note: As of June 2026, I had stopped manually tracking the count after 4,000 chat turns. At that point, the broader Syx design and implementation history was likely above 5,000 turns.

It is hard to explain how powerful that was without seeing it. The AI was no longer just answering from the current chat. It was able to pull from months of prior discussion, design decisions, abandoned ideas, and refinements. That was when I realized this might be more than an interesting experiment.

Second, the proof of concept had answered enough of the hard questions that I could see a path to building a real prototype.

That was the point where the project changed from “can this work?” to “how should this be built?”

## Building the Prototype

After the third proof-of-concept iteration, I decided the idea was workable enough to build as a real prototype.

The prototype became Syx: a local AI memory system built around project-based memory, daily chat rolloff, long-term retrieval, sleep-cycle consolidation, markdown memory artifacts, and eventually read-only memory access for agents.

The rest of the repository documents the current implementation. This history is included only to explain how the project moved from a neuroscience-inspired question to a working prototype.