---
name: quick-pr
description: "All-in-one: stage, commit, push, open PR, resolve merge conflicts, and merge — single command end to end."
tools: Read, Grep, Glob, Bash, Write
---

End-to-end PR flow for the current working tree. Handles staging, committing, pushing, conflict resolution, PR creation, and merge.

`$ARGUMENTS` — optional commit message. If omitted, derive one from the diff.

## Step 1: Sanity check

```bash
git status
git diff main...HEAD --stat 2>/dev/null || git diff --stat HEAD
```

If the working tree is clean and there are no unpushed commits, stop and tell the user — nothing to do.

## Step 2: Stage and commit (if there are unstaged/uncommitted changes)

```bash
git diff --name-only          # unstaged
git diff --cached --name-only # already staged
```

Stage all modified and new tracked files (do NOT use `git add -A` blindly — list files first and skip anything that looks like secrets, `.env`, or large binaries).

Draft a commit message:
- If `$ARGUMENTS` provided: use it verbatim
- Otherwise: derive from the diff — imperative mood, under 72 chars, `type: description (LIN-{id})` if the branch is `feature/lin-{id}-*`

Show the staged file list and commit message. Ask: **"Commit with this message? (y/n)"** — wait for confirmation before running `git commit`.

```bash
git commit -m "<message>"
```

## Step 3: Push

```bash
git push -u origin HEAD
```

If push is rejected (non-fast-forward), pull with rebase first:

```bash
git pull --rebase origin main
```

If rebase hits conflicts:
1. Run `git diff --name-only --diff-filter=U` to list conflicted files
2. Read each conflicted file
3. Resolve by keeping the correct version (explain the choice)
4. `git add <file>` each resolved file
5. `git rebase --continue`
6. Retry push

## Step 4: Draft PR content

Apply `.claude/skills/code_pr.md`:

```bash
git log main...HEAD --oneline
git diff main...HEAD --stat
```

Read the active plan if present:
```bash
cat .claude/docs/SESSION.md 2>/dev/null
```

Write PR title and description per `code_pr.md` conventions. If branch is `feature/lin-{id}-*`, title must be `LIN-{id} {description}`.

Show the full title and body. Ask: **"Open PR with this content? (y/n)"** — wait for confirmation.

## Step 5: Open PR

```bash
gh pr create \
  --title "<title>" \
  --body "<body>" \
  --base main
```

Print the PR URL.

## Step 6: Merge (optional)

Ask: **"Merge now? (y/n/squash)"**

- `y` → `gh pr merge --merge --delete-branch`
- `squash` → `gh pr merge --squash --delete-branch`
- `n` → stop, leave PR open for review

If merge fails due to conflicts, fetch the PR's merge conflicts:
```bash
gh pr checkout <number>
git merge main
```
Resolve conflicts (same approach as Step 3), push, then retry merge.

## Rules

- Never force-push (`--force`) unless the user explicitly asks
- Never skip hooks (`--no-verify`)
- Never commit `.env`, `*.pem`, `models/*.pkl`, or any file over 10 MB
- If any step fails unexpectedly, stop and report the error — do not attempt workarounds silently
