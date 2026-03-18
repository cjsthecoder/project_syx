# Test Setup and Execution

## ChatGPT Setup

Create a new Project.  When you create it, select Settings and change setting Memory to 'Project Only'

Manually change the model to ChatGPT 5.2 Instant.

### In Project Settings add this for instructions:

====== ASSISTANT_HINT ======
Follow these preferences: tone=creative, verbosity=balanced, format=markdown, domain_focus=['story creation', 'world building', 'sci-fi']. Respond concisely in the chosen format.


### In Settings/Personalization under Custom Instructions add this:

You are helping develop an original hard science fiction story. Maintain continuity across turns. Reuse established names, factions, technologies, locations, and story facts unless the user explicitly changes them. Prefer grounded scientific reasoning, clear structured outputs, and internally consistent world building.


## Morpheus Setup

### Verify these settings are set:
FORCE_RAG_REBUILD_ON_STARTUP=false
INSTRUMENTATION_ENABLED=true
INSTRUMENTATION_MODE=metrics
INSTRUMENTATION_RUN_ID=test_run
INSTRUMENTATION_RUNS_DIR=runs
INSTRUMENTATION_PROMPT_TOL_ABS_TOKENS=25
ENABLE_DREAM=false
GENERATE_DEBUG_FILES=true

make setup-env

### Steps
start Morpheus (make run)
Create a new Project "Test Run" (or something unique for a test)

Click the Manage button
Click Personality button (on Manage window)

In System Prompt add this:

You are helping develop an original hard science fiction story. Maintain continuity across turns. Reuse established names, factions, technologies, locations, and story facts unless the user explicitly changes them. Prefer grounded scientific reasoning, clear structured outputs, and internally consistent world building.

Change Tone to Creative
Change Verbosity to balanced
Leave Format as md

Slide the Creativity bar to .8

Under Domain Focus (comma-separated) add:
story creation, world building, sci-fi

Save/Close

## Test Execution

For each prompt in the prompts.json file, cut and paste the prompt in one at a time into Morpheus first.
Make sure to let each prompt finish, and tag before executing the next prompt.

Once all the prompts are executed in Morpheus, quit the run.

In the ChatGPT Project also cut and paste each prompt from prompts.json.
Let each prompt completely finish before pasting/entering the next one.

Once all prompts are complete.  Right click in the chat area of the browswer.
Select Save Page As....

Note the filename and the location so you can find it.

## Processing

On the command line execute (from morpheus root):
% python3 tools/extract_chat.py  <prompts.json> <chat_export.html> <test_run_path>

On the command line execute (from morpheus root):
% python3 tools/build_judge_input.py <test_run_path>



