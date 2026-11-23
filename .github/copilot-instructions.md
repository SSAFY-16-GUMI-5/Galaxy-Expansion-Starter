# Repository-wide Copilot instructions

Read `AGENTS.md`, `docs/ASSIGNMENT.md`, and `docs/PROTOCOL.md` before modifying code.
The chosen programming language is participant-defined. Put language-specific code under `solution/`.
Keep the Galaxy JSONL v1 contract fixed, stdout JSON-only, and diagnostics on stderr.
First generate a runnable scaffold and leave the actual Object Pool implementation as TODO unless the participant explicitly requests implementation help.
Add language-native tests proving real instance/storage reuse. Do not edit `contracts/`, `scripts/`, or baseline CI to bypass failing checks.
Report concrete commands run and tests passed/failed; never claim unexecuted checks succeeded.
