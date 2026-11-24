# Repository-wide Copilot instructions

Read `AGENTS.md`, `docs/ASSIGNMENT.md`, and `docs/PROTOCOL.md` before modifying code.
The chosen programming language is participant-defined. Put language-specific code under `solution/`.
Keep the Galaxy JSONL v1 contract fixed, stdout JSON-only, and diagnostics on stderr.
First generate a runnable scaffold and leave the actual Object Pool implementation as TODO unless the participant explicitly requests implementation help.
Write runnable language-native tests in `solution/`. Cover real instance/storage reuse after release, property reinitialization, and double release without corrupting the pool.
Keep these tests runnable while the pool implementation is TODO. Explain any expected failures and the behavior the participant needs to implement.
Create or update `.github/workflows/solution-<lang>.yml` to run the build when applicable, native tests, and `node scripts/verify-protocol.mjs -- <command>` on pull requests without a live relay or token.
Keep `contracts/`, `scripts/`, and baseline `.github/workflows/verify.yml` intact.
Report concrete commands run and tests passed/failed; never claim unexecuted checks succeeded.
