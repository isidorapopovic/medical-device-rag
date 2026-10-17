# Codex in VS Code — usage

1. Open your actual repository in Visual Studio Code (not the separate Visual Studio IDE). Copy the contents of this pack to a directory within the repository, keeping the repo's actual README and AGENTS.md intact. If an AGENTS.md already exists, merge the safety/implementation instructions rather than replacing it.
2. Prefer a separate git feature branch and clean working tree before large changes. Take a backup of any real documents or indexes.
3. In the Codex IDE extension select an agent/editing mode with workspace write permissions. Use the best available permission preset that can run routine local tests without unrestricted file/network access. Do not select Full Access merely to avoid routine confirmations.
4. Paste `codex_prompts/MASTER_RUN_ALL_STAGES.md` into the Codex chat. It will read the stage documents and advance if gates pass. A single Codex session is **not guaranteed** to finish an entire multiweek project: context, tools, approvals, quotas or runtime may interrupt it.
5. After any interruption, start a fresh Codex conversation and paste `codex_prompts/RESUME_AFTER_INTERRUPTION.md`. Inspect `docs/implementation/PROGRESS.md` and git diff yourself.
6. For maximum control, send `codex_prompts/PROMPT_00.md`, review tests, then `PROMPT_01.md` and so on. Never let the model claim regulatory validation without expert data.

Using Codex via the ChatGPT account is different from making OpenAI API calls from your application. The pack defaults the application to local Ollama and offline tests. Avoid automatic model downloads and cloud inference.
