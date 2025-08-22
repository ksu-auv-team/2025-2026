# Git Usage & Etiquette — Freshman-Friendly Cheatsheet

Welcome! This sheet covers the *core* Git commands you’ll use daily and the etiquette that keeps teammates happy. Keep it handy during labs & projects.

---

## 1) One-Time Setup (per machine)

```bash
# identify yourself (shows up in commit history)
git config --global user.name "Your Name"
git config --global user.email "you@school.edu"

# quality of life
git config --global init.defaultBranch main
git config --global pull.rebase false         # safer for beginners
git config --global core.editor "code --wait" # or nano/vim
git config --global color.ui auto
```

---

## 2) Starting a Project

```bash
# new repo from scratch
mkdir my-project && cd my-project
git init
echo "# My Project" > README.md
git add README.md
git commit -m "Initialize repo with README"

# OR clone an existing repo
git clone https://github.com/org/repo.git
cd repo
```

---

## 3) Everyday Workflow (feature branches)

```bash
# make sure main is current
git checkout main
git pull                    # update local main

# create a feature branch off main
git checkout -b feature/login-form

# work normally, add and commit in small chunks
git add src/Login.jsx
git commit -m "Add basic login form component"

# push your branch to the remote
git push -u origin feature/login-form

# open a Pull Request (PR) on GitHub/GitLab, get review, then merge
```

---

## 4) Staging & Committing

```bash
git status                 # see what changed
git add <file>             # stage a file
git add -p                 # interactively stage parts (advanced but useful)
git commit -m "Short, imperative summary"
git commit                 # opens editor for multi-line message
```

**Good commit message format**

```
Add login form validation

- Validate email format and password length
- Show inline error messages
- Add unit tests for validators
```

**Rule of thumb:** one logical change per commit; make commits small and frequent.

---

## 5) Syncing With Remote

```bash
git pull                   # fetch + merge remote changes into current branch
git fetch                  # just download refs; no merge
git push                   # upload your commits
```

> Tip: If your branch is behind `origin/main`, update it before opening a PR:

```bash
git checkout feature/login-form
git merge main             # or: git rebase main (advanced; keep history linear)
```

---

## 6) Branching & Merging

```bash
git branch                 # list local branches
git branch -r              # list remote branches
git checkout -b feature/x  # new branch from current
git switch feature/x       # alternative to checkout for branches
git merge feature/x        # merge feature/x into current branch
```

**Fast-forward vs merge commit**

* If no diverging commits: Git will fast-forward (no extra merge commit).
* If diverged: Git creates a merge commit or asks you to resolve conflicts.

---

## 7) Resolving Merge Conflicts (quick guide)

When Git shows conflict markers in files:

```
<<<<<<< HEAD
your change
=======
their change
>>>>>>> main
```

Steps:

```bash
# 1) Open files, choose/merge the correct lines
# 2) Mark resolved:
git add <conflicted-file>
# 3) Complete the merge:
git commit
```

> If stuck, you can cancel a merge: `git merge --abort`

---

## 8) Stashing (save changes without committing)

```bash
git stash                   # stash tracked changes
git stash push -u           # include untracked files too
git stash list
git stash apply             # reapply latest (keeps stash)
git stash pop               # reapply and drop
```

---

## 9) Undo / Fix Mistakes (safely)

```bash
git restore <file>          # discard WORKING COPY changes to a file
git restore --staged <file> # unstage (keeps changes)
git revert <commit>         # make a new commit that undoes a specific commit
git reset --soft HEAD~1     # move HEAD back 1 commit, keep changes staged
git reset --hard HEAD~1     # ⚠️ delete last commit & changes locally
```

> **Never** use `--hard` or `--force` on shared branches unless you are 110% sure and your team agrees.

---

## 10) Inspecting History & Differences

```bash
git log --oneline --graph --decorate --all
git show <commit>           # view a specific commit
git diff                    # see unstaged changes
git diff --staged           # see staged changes
git blame <file>            # who changed which line (use respectfully)
```

---

## 11) .gitignore Basics

Create a `.gitignore` to avoid committing junk:

```
# OS / editor
.DS_Store
*.swp
.vscode/
.idea/

# deps / builds
node_modules/
dist/
__pycache__/
*.pyc

# secrets
.env
*.key
*.pem
```

> Add before committing! If something is already tracked, run:

```bash
git rm -r --cached <path>
git commit -m "Stop tracking generated files"
```

---

## 12) Tags (optional but handy)

```bash
git tag v1.0.0                 # lightweight tag
git tag -a v1.0.0 -m "Release" # annotated
git push origin v1.0.0
git tag                        # list tags
```

---

## 13) Collaboration Etiquette (do this!)

* **Use feature branches.** Don’t commit directly to `main` (in team projects).
* **Small, focused commits.** Easier to review, test, and revert.
* **Write meaningful messages.** Use imperative mood: “Add X”, “Fix Y”.
* **Pull before you push.** Reduce conflicts: `git pull` before `git push`.
* **Avoid `git push --force` on shared branches.** If necessary, coordinate with your team (`--force-with-lease` is safer).
* **Don’t commit secrets or large binaries.** Use `.env`, Git LFS, or cloud storage.
* **Open clear PRs.** Title: purpose; Description: what/why/how to test.
* **Review kindly & specifically.** Comment on code, not people. Suggest improvements.
* **Resolve conflicts locally.** Don’t commit conflict markers.
* **Keep your name/email consistent.** Prevent “unknown author” history.
* **Ask before rewriting history.** Especially after a PR is opened.
* **Respect the CI.** Fix failing checks before requesting review.

---

## 14) Common Errors & Quick Fixes

**“fatal: not a git repository”**
You’re outside a repo → `git init` (new) or `cd` into the cloned directory.

**“Permission denied (publickey)” when pushing**
Set up SSH keys or use HTTPS; on SSH: `ssh-keygen -t ed25519`, add public key to Git host.

**Pushed wrong branch to origin**

```bash
# delete remote branch (if safe):
git push origin --delete wrong-branch
```

**Accidentally committed secrets**

1. Remove the file + rotate the secret.
2. Add to `.gitignore`.
3. If already pushed, you may need history rewrite tools (ask a TA).

**Detached HEAD**
You checked out a commit instead of a branch. Create a branch:

```bash
git switch -c fix/detached
```

---

## 15) Minimal Git/GitHub Classroom Flow

1. **Accept assignment** → repo is created for you.
2. `git clone <assignment-repo-url>`
3. Work on `feature/<your-name>` branch.
4. Commit frequently; push branch.
5. Open PR into `main` before the deadline.
6. Address review comments; merge when green.

---

## 16) Quick Reference (Top 15)

```bash
git status
git add <file> | -A | -p
git commit -m "Message"
git pull
git push
git checkout -b feature/x
git switch <branch>
git merge main
git log --oneline --graph --decorate --all
git diff | git diff --staged
git stash / git stash pop
git restore <file> | --staged <file>
git revert <commit>
git tag -a vX.Y.Z -m "Release"
git rm -r --cached <path>
```

---

## 17) Keep Learning

* Practice with a sandbox repo. Break things, then fix them.
* Try `gitk` or VS Code’s Source Control view to visualize history.
* Learn `rebase` *after* you’re comfortable with merge.

---

### Print-Friendly Tip

Export this page to PDF or keep it in your project’s `docs/` folder as `GIT_CHEATSHEET.md`.
Good luck, and happy committing! 🚀
