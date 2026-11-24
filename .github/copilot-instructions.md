# Repository-wide Copilot instructions

Read `AGENTS.md`, `docs/ASSIGNMENT.md`, and `docs/PROTOCOL.md` before modifying code.
The chosen programming language is participant-defined. Put language-specific code under `solution/`.
Keep the Galaxy JSONL v1 contract fixed, stdout JSON-only, and diagnostics on stderr.
Ask what the participant wants to implement and what design they are considering. Discuss trade-offs, let them choose the design, and agree on one small step at a time.
Use questions, hints, pseudocode, or short examples to coach the participant through writing the core Acquire/Release logic themselves. Keep core logic as TODO in any scaffold. If asked for code help, write the relevant part together and explain the change.
Agree on inputs and expected results before writing runnable language-native tests together in `solution/`. Cover real instance/storage reuse after release, property reinitialization, and double release without corrupting the pool.
Keep these tests runnable while the pool implementation is TODO. Explain any expected failures and the behavior the participant needs to implement.
Create or update `.github/workflows/solution-<lang>.yml` to run the build when applicable, native tests, and `node scripts/verify-protocol.mjs -- <command>` on pull requests without a live relay or token.
Keep `contracts/`, `scripts/`, and baseline `.github/workflows/verify.yml` intact.
Report concrete commands run and tests passed/failed; never claim unexecuted checks succeeded.
