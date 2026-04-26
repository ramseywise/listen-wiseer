---
name: branch
description: "Create a feature branch, stage changes, and commit — without opening a PR."
tools: Read, Grep, Glob, Bash
---

Create a feature branch and commit current (or specified) changes to it.

`$ARGUMENTS` — required. Format: `<slug> [commit message]`
- `slug` — short kebab-case description, e.g. `add-snippet-db`
- `commit message` — optional; derived from diff if omitted

Branch name is built from the Linear issue ID on the current branch (if any) or left as `feature/<slug>`.

## Step 1: Check for a Linear ID

```bash
git branch --show-current
```

If current branch is `feature/lin-{id}-*`, carry the ID to the new branch: `feature/lin-{id}-<slug>`.
Otherwise: `feature/<slug>`.

## Step 2: Check working tree

```bash
git status
git stash list
```

If the tree is clean and there's nothing stashed, stop — nothing to commit.

## Step 3: Create and switch to branch

```bash
git checkout -b feature/<slug>   # or feature/lin-{id}-<slug>
```

If the branch already exists, switch to it:
```bash
git checkout feature/<slug>
```

## Step 4: Stage files

```bash
git diff --name-only
git diff --cached --name-only
```

List files to stage. Skip secrets, `.env`, large binaries (>10 MB), and notebook output cells.

Show the file list. Ask: **"Stage these files and commit? (y/n)"** — wait for confirmation.

```bash
git add <files...>
```

## Step 5: Commit

Draft commit message:
- If provided in `$ARGUMENTS`: use verbatim
- Otherwise: derive from diff — `type: description (LIN-{id})` if Linear ID present, else `type: description`
- Imperative mood, under 72 chars

```bash
git commit -m "<message>"
```

Print the commit hash and message on success.

## After

To push and open a PR later, run `/quick-pr`.

## Rules

- Never force-push or amend published commits
- Never commit `.env`, `*.pem`, `models/*.pkl`, or files over 10 MB
- Never skip hooks (`--no-verify`)
