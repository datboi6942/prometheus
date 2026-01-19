Prometheus Agent Guidelines
Step 1: The Pulse Check When you start a task, verify the current active model via the config.yaml. If you are a local model, prioritize efficiency and diff-based edits to save VRAM.

Step 2: The Forge (Execution)

Propose changes using Unified Diff format.

If a command needs to be run, output it in a bash block and explain what it does.

Use the filesystem_write tool instead of rewriting the whole file.

Step 3: The Audit After every code change, trigger the test_runner tool. If tests fail, you must analyze the logs, propose a fix, and re-run until passing.

STEP 4: ONCE ALL CHANGES HAVE BEEN MADE OR A NEW FEATURE IS ADDED OR A REFACTOR IS DONE IT IS IMPERATIVE THAT YOU COMMIT THE CHANGES TO A BRANCH SPECIFIC TO THE CHANGES AND SUBMIT A PULL REQUEST ON GITHUB SO THAT IT GETS REVIEWED BY GREPTILE