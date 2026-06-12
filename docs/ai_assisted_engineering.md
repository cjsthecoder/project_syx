# AI-Assisted Engineering

Syx was built with AI-assisted software engineering, but not by treating the AI as the source of product truth.

This process is intentionally not “vibe coding.” The AI is not asked to invent the product from a vague prompt. Requirements are developed first, ambiguities are surfaced and answered, implementation is tied back to accepted requirements or deltas, and tests are used to verify behavior.

This document explains that workflow so future contributors, reviewers, and technical readers can understand how the codebase evolved and how new changes should be clarified before implementation.

## Why This Matters

Syx is a memory system about long-running context. Building it also required a long-running engineering context.

The project accumulated architecture decisions, requirements, implementation details, exceptions, corrections, and follow-up changes over many sessions. That is exactly the kind of situation where AI tools are useful, but also exactly the kind of situation where they can drift if there is no stable source of truth.

Without written requirements, an AI coding assistant can easily:

* Reintroduce behavior that was already changed.
* Treat old design notes as current requirements.
* Implement plausible but undocumented behavior.
* Miss the difference between accepted baseline behavior and active design work.
* Preserve compatibility with code or behavior that was never intended to ship.
* Broaden a change beyond what was actually requested.

Syx uses written requirements, deltas, tests, and coding rules to keep that from happening.

## Adapting This Process to Teams

This process is written from the perspective of a solo open source project, but the pattern is not limited to that.

In a team environment, `DELTAS.md` could be replaced or supplemented by Jira tickets, GitHub Issues, Linear issues, design docs, ADRs, or pull request plans. The important part is not the specific file. The important part is that each AI-assisted implementation has a bounded, reviewable source of truth before code changes begin.

For Syx, `REQUIREMENTS.md` provides the accepted baseline and `DELTAS.md` provides the active change layer. In a larger team, the same pattern could map to:

* baseline requirements or architecture docs
* release milestones or epics
* ticket-scoped change descriptions
* affected requirement or component references
* explicit non-goals
* open questions
* accepted answers
* test or acceptance criteria

The exact files are not the point. The control loop is the point.

The goal is to keep AI-assisted work tied to reviewed intent, whether that intent lives in markdown files, issue trackers, or formal engineering documents.

## The Starting Point: Requirements in Context

Most meaningful Syx changes start in a long-running AI chat that has access to the project history.

That matters because the chat is not starting from zero. It has access to prior design decisions, rejected ideas, terminology, architecture boundaries, and earlier tradeoffs. I use that context to work through the requirement before asking the coding assistant to implement anything.

This is where the human is very much in the loop because experience matters. The AI may suggest designs, alternatives, tradeoffs, or implementation paths, but those suggestions are not automatically accepted. I regularly reject suggestions, narrow the scope, change terminology, defer ideas to future work, or ask the AI to try again from a different direction.

The design work continues until I am comfortable that the requirement reflects what I actually want built.

This stage usually includes:

* Describing the problem or feature.
* Comparing it to prior decisions.
* Deciding whether the change belongs in the current release.
* Accepting, rejecting, or revising AI-suggested approaches.
* Identifying what should not change.
* Writing acceptance criteria.
* Clarifying architecture boundaries.
* Deciding whether the change updates the baseline requirements or needs a delta.

The goal is not to generate code yet. The goal is to make the requirement clear enough that implementation does not depend on guessing.

## Release-Oriented Requirements

`REQUIREMENTS.md` is organized around release-sized versions.

Each version defines a purpose, then breaks that purpose into functional requirements. Each functional requirement is intended to be small enough for an AI coding assistant to analyze, clarify, implement, and test as a bounded unit of work.

This is close to a conventional software workflow. In a team environment, a version could map to a milestone or epic, and each functional requirement could map to a Jira ticket, GitHub Issue, Linear issue, or pull request plan.

The size of a requirement matters. If a requirement is too small, the AI assistant may lack enough context to implement the behavior correctly. If it is too large, the assistant may ask too many clarification questions or mix unrelated concerns. Part of the process is learning how much work fits into one requirement or delta.

For Syx, the requirement IDs provide stable handles for AI-assisted work. They let me ask questions such as:

```text
Which existing requirements does this delta modify?
Which requirement IDs are directly affected?
Does this implementation satisfy FR-003?
Does this change broaden the accepted scope of FR-004?
```

## REQUIREMENTS.md

[`docs/REQUIREMENTS.md`](REQUIREMENTS.md) is the consolidated as-built specification for Syx.

It describes accepted system behavior, functional requirements, technical requirements, architecture expectations, configuration rules, and acceptance criteria.

Use `REQUIREMENTS.md` when the behavior is part of the current accepted system design.

It is not just background reading. It is the contract for how the system is expected to behave after prior requirement work has been folded into the project.

During development, this file serves several purposes:

* It gives AI-assisted implementation a stable target.
* It preserves feature intent across many implementation sessions.
* It makes acceptance criteria explicit enough to test and review.
* It keeps architectural boundaries visible.
* It reduces the chance that older design conversations override current decisions.

## DELTAS.md

[`docs/DELTAS.md`](DELTAS.md) exists because new requirements often touch existing requirements.

`REQUIREMENTS.md` describes the accepted as-built system. That is useful for stable behavior, but it creates a specific AI-assisted engineering problem: when a new change overlaps older requirements, the coding assistant needs to know exactly what is changing without being invited to reinterpret or rewrite the entire baseline.

A delta gives the change a focused working surface.

Instead of immediately restructuring `REQUIREMENTS.md`, I can write a delta that describes the proposed change, maps it to directly affected requirement IDs, identifies what older behavior is modified or superseded, and records the questions that need to be answered before implementation.

This gives the AI coding assistant a bounded task. It can analyze the delta against the baseline, find ambiguity, ask focused questions, and update only the delta based on the answers. The assistant is not asked to infer a new architecture from the whole requirements file.

That is the main reason `DELTAS.md` exists. It keeps the baseline requirements stable while still giving AI-assisted implementation a safe place to evolve the design.

A good delta explains:

* What behavior is changing.
* Why the change exists.
* Which requirement IDs are directly affected.
* Which older behavior is modified or superseded.
* What is in scope.
* What is explicitly out of scope.
* What must not be broadened.
* What questions still need to be answered.
* What answers were accepted.
* How the change should be validated.

A delta is usually the right place for a change when it:

* Modifies behavior already described in `REQUIREMENTS.md`.
* Supersedes part of an older requirement.
* Crosses subsystem boundaries.
* Needs clarification before implementation.
* Should not be folded into the baseline until it is accepted.

When `REQUIREMENTS.md` and `DELTAS.md` conflict, an accepted delta controls the current implementation work.

Once a feature-sized delta is implemented, tested, reviewed, and accepted, the accepted behavior is folded back into `REQUIREMENTS.md`. This keeps `REQUIREMENTS.md` as the current baseline while allowing `DELTAS.md` to stay focused on active or recently completed change work.

After a delta is folded into the baseline, it can be removed, archived, or retained only as design history.

## The Clarification Loop

After a requirement or delta is drafted, I ask the coding assistant to analyze it before implementation.

This is an important step. The AI is not being asked to write code yet. It is being asked to find ambiguity.

A typical prompt looks like this:

```text
Analyze DELTA-A.4.4 with the existing codebase in mind.
Ask only the questions that are required to implement this delta correctly.
Assume conservative, rebuild-on-error semantics unless explicitly stated otherwise.
Number the questions and place all questions in questions.txt.
Do not ask implementation-detail questions unless they affect correctness.
```

The `questions.txt` file is only a temporary scratch pad, not an authoritative project artifact. I use it because it is easier to read, answer, and revise a numbered question list in a separate file than inside the chat or a long requirements document. Once the questions are answered, the accepted answers should be folded into the relevant requirement or delta. At that point, `questions.txt` should not be treated as project documentation or as part of the project specification. In this repository, `questions.txt` is ignored by Git so it can be used as local scratch space without becoming part of the public documentation set.

The exact prompt changes depending on the work, but the pattern is the same:

1. Point the AI at the specific requirement or delta.
2. Ask it to identify affected requirements.
3. Ask it to avoid speculative scope.
4. Ask it to find ambiguity.
5. Ask it to write numbered questions.
6. Answer the questions manually.
7. Ask whether more questions remain.
8. Repeat until the requirement is clear enough to implement.

The number of questions is useful feedback. If there are only a few, the requirement is usually close. If there are many, that usually means the requirement still has hidden ambiguity or scope problems.

## Updating the Requirement or Delta

After the questions are answered, the next step is to update the requirement or delta.

The coding assistant is asked to apply only the clarified answers. It should not broaden the scope, rewrite unrelated sections, or restate large parts of the baseline requirements.

The goal is to turn the requirement into something implementation-ready.

At this point, a delta should normally have:

* Clear intent.
* Clear affected requirement IDs.
* Clear scope.
* Clear non-goals.
* Clear accepted answers to open questions.
* Clear test or verification expectations.
* Status marked appropriately.

Only after that does implementation start.

## Implementation

Once the requirement or delta is clear, I ask the coding assistant to implement it.

At this point the implementation usually works well because the hard part has already happened. The ambiguity has been pulled forward into the requirement phase instead of being discovered halfway through the code change.

In practice, the implementation step is often fast:

1. The requirement is clear.
2. The affected files are easier to identify.
3. The assistant has fewer reasons to guess.
4. Tests can be mapped back to acceptance criteria.
5. Review can focus on whether the code matches the written intent.

This process sounds heavier than it is. Most changes do not require a large number of questions. When the requirement is clear, the loop is quick.

It also creates a useful separation of work. While the coding assistant is implementing an accepted requirement or delta, I can continue working through the next requirement in the project-aware chat. That keeps design work and implementation work moving in parallel without mixing unfinished decisions into the code change already underway.

## Coding Rules and Standards

Syx also uses coding rules to keep AI-assisted implementation consistent.

These rules cover areas such as:

* Function size and single-responsibility design.
* API handler boundaries.
* Retrieval and memory lifecycle boundaries.
* Logging expectations.
* Exception handling.
* Security-sensitive output.
* Test expectations.
* Documentation expectations.
* Frontend structure.
* Provider and embedding factory usage.

The point is not to make every file perfect. The point is to keep implementation from drifting across repeated AI-assisted edits.

For example, an AI assistant may be able to implement a feature in one large function, but the project rules can require smaller functions, clearer boundaries, safer logging, and tests that match the intended behavior.

## How AI Is Used

AI assistance is used for tasks such as:

* Clarifying requirements.
* Finding ambiguity.
* Mapping deltas to affected requirement IDs.
* Implementing features from written requirements.
* Refactoring broad code into smaller functions.
* Writing and updating tests.
* Reviewing stale documentation.
* Reconciling implementation behavior with requirements.
* Drafting public documentation.
* Checking whether a change broadened beyond its intended scope.

The intended pattern is not:

```text
Ask the AI to invent the product.
```

The intended pattern is:

```text
Use AI to help implement and review a product whose intent is written down.
```

## Development Flow

A typical Syx change follows this path:

1. Work through the design in a project-aware AI chat.
2. Decide whether the change belongs in `REQUIREMENTS.md` or `DELTAS.md`.
3. Draft or update the requirement or delta.
4. Ask the coding assistant to identify affected requirements and open questions.
5. Answer the questions.
6. Repeat until there are no important unanswered questions.
7. Ask the coding assistant to update the requirement or delta based only on the answers.
8. Ask the coding assistant to implement the accepted requirement or delta.
9. Run tests.
10. Add or update tests if behavior changed.
11. Review the implementation against the written requirement.
12. Update public documentation if user-visible behavior changed.

## Contributor Expectations

Contributors do not need to use AI tools. But if they do, they should still treat the written project documents as the authority.

Before opening a pull request that changes behavior:

* Read [`docs/REQUIREMENTS.md`](REQUIREMENTS.md).
* Read [`docs/DELTAS.md`](DELTAS.md).
* Check focused docs such as [`docs/architecture.md`](architecture.md), [`docs/memory_lifecycle.md`](memory_lifecycle.md), [`docs/sleep_cycle.md`](sleep_cycle.md), [`docs/dream_cycle.md`](dream_cycle.md), and [`docs/agent_interface.md`](agent_interface.md).
* Update tests when behavior changes.
* Update docs when requirements, configuration, public APIs, or workflows change.
* Do not commit private runtime data, memory artifacts, logs, debug files, generated indexes, `.env` files, or secrets.

## What This Process Does Not Mean

AI-assisted engineering does not remove the need for judgment.

It does not mean:

* AI output is accepted without review.
* Requirements are frozen forever.
* Deltas are permanent side channels.
* Tests exist only to satisfy coverage numbers.
* Documentation can drift away from implementation.
* The AI decides the architecture.
* Every idea belongs in the current release.

The goal is the opposite: make the project easier to change by keeping intent, implementation, and reviewable evidence close together.

## Practical Rule

If a future change would make a reader ask “which document is true?”, clarify that before implementation.

Either fold the accepted behavior into [`docs/REQUIREMENTS.md`](REQUIREMENTS.md), or write a clear delta in [`docs/DELTAS.md`](DELTAS.md) that explains what changed, what it supersedes, and what must not be broadened.
