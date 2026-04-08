# Sync Upstream

Fetch and merge commits from `upstream/main` into the current branch, then resolve any conflicts.

## Steps

1. **Verify upstream remote exists**
   ```bash
   git remote -v
   ```
   If `upstream` is not listed, ask the user for the upstream URL and add it:
   ```bash
   git remote add upstream <url>
   ```

2. **Check for uncommitted changes** — if any exist, warn the user and stop. Do not proceed with a dirty working tree.

3. **Fetch upstream**
   ```bash
   git fetch upstream
   ```

4. **Show what's new** — list commits in upstream/main that are not in HEAD:
   ```bash
   git log --oneline HEAD..upstream/main
   ```
   If there are no new commits, tell the user and stop.

5. **Attempt the merge**
   ```bash
   git merge upstream/main --no-edit
   ```

6. **If conflicts occur:**
   - List conflicted files: `git diff --name-only --diff-filter=U`
   - For each conflicted file, read it and resolve the conflict by choosing the appropriate version or combining both sides intelligently. General rules:
     - **Our fork-specific changes** (e.g. JLCPCB live API, custom tools) → keep HEAD
     - **New upstream features** (e.g. new tools, new docs sections) → include from upstream
     - **Documentation files** where both sides added new sections → merge both sections
     - When in doubt, prefer keeping our changes and adding upstream's new content alongside
   - After resolving, `git add` the resolved files
   - Complete the merge with `git commit`

7. **Summarize** — report what was merged (commit list) and how any conflicts were resolved.

## Notes

- Never use `git merge -X ours` or `git merge -X theirs` blindly — always read the conflicts first
- This repo's upstream is `https://github.com/mixelpixx/KiCAD-MCP-Server`
- Our fork adds: JLCPCB live API integration, extra schematic/LLM tools, custom skill files
- Do NOT push after merging — ask the user first
