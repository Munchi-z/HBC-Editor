# HBCE — GitHub Push Guide
## How to update your repo + get commits to show on your profile

---

## 🔴 WHY YOUR COMMITS DON'T SHOW UP

GitHub only counts a commit on your profile graph **if the email in that commit
matches a verified email on your GitHub account.**

Fix it once — all future commits will count.

---

## ✅ ONE-TIME FIX: Set your git identity

Open a terminal / Git Bash in your HBCE project folder and run:

```bash
# Replace with your REAL GitHub email (the one on your GitHub account)
git config --global user.name  "Munchi-z"
git config --global user.email "YOUR_GITHUB_EMAIL@example.com"
```

> **How to find your GitHub email:**
> GitHub → Settings → Emails → copy the primary address shown there.
> If you use "Keep my email private", use the `@users.noreply.github.com`
> address GitHub shows you on that page instead.

Verify it was saved:
```bash
git config --global user.name
git config --global user.email
```

---

## 🚀 HOW TO PUSH V0.1.2a-alpha TO GITHUB

Run these commands from inside your project folder (where `main.py` lives):

```bash
# 1. Stage everything
git add .

# 2. Commit with a descriptive message
git commit -m "feat: Backup/Restore panel — full implementation V0.1.2a-alpha

- ARCH-011 restore flow: diff preview → typed RESTORE confirm → pre-restore backup → write
- BackupThread / RestoreThread / DiffThread (GOTCHA-013 compliant)
- Diff viewer with colour-coded unified diff (difflib)
- Auto-backup on device connect, retention settings, import/export .hbce-bak
- CSV export of backup log
- trigger_auto_backup() public API for comms layer
- Version bumped to V0.1.2a-alpha"

# 3. Push to GitHub
git push origin main
```

---

## 🏷️ HOW TO TRIGGER THE .EXE BUILD + RELEASE

The CI builds a Windows `.exe` and zips it automatically when you push a tag.

```bash
# Tag the release (must start with 'v' to trigger the release workflow)
git tag v0.1.2a-alpha

# Push the tag
git push origin v0.1.2a-alpha
```

After ~5 minutes, go to:
**GitHub → your repo → Actions** to watch the build.

When it finishes, the zip will appear at:
**GitHub → your repo → Releases → HBCE v0.1.2a-alpha**

The zip is named:  `HBCE-v0.1.2a-alpha-windows.zip`
Inside it:         `HBCE\HBCE.exe`  + all dependencies

---

## 🔁 EVERY FUTURE SESSION — STANDARD WORKFLOW

```bash
# After every coding session:
git add .
git commit -m "your message here"
git push origin main

# When you want a new .exe release:
git tag v0.X.Xx-alpha
git push origin v0.X.Xx-alpha
```

---

## 🛠️ IF YOU GET A PUSH ERROR

**"Permission denied" or "Authentication failed":**
```bash
# Use a Personal Access Token (PAT) instead of your password
# GitHub → Settings → Developer Settings → Personal Access Tokens → Tokens (classic)
# Create one with: repo (full control)
# Then when git asks for password, paste the token
```

**"Updates were rejected" (your remote has changes you don't have):**
```bash
git pull origin main --rebase
git push origin main
```

**First push to a brand new repo:**
```bash
git remote add origin https://github.com/Munchi-z/HBC-Editor.git
git branch -M main
git push -u origin main
```

---

## 📊 VERIFY YOUR COMMITS ARE LINKED TO YOUR ACCOUNT

After pushing, go to:
`https://github.com/Munchi-z/HBC-Editor/commits/main`

Click any commit. If your avatar appears next to it — it's linked to your account
and **will count on your contribution graph.**

If it shows a grey ghost icon, the email didn't match. Re-check step 1.

---

## 🔄 FIX OLD COMMITS (optional)

If you have old commits that used the wrong email, you can rewrite them.
Only do this if the repo is yours alone (rewrites history):

```bash
git filter-branch --env-filter '
OLD_EMAIL="wrong@email.com"
NEW_EMAIL="your_github_email@example.com"
NEW_NAME="Munchi-z"
if [ "$GIT_COMMITTER_EMAIL" = "$OLD_EMAIL" ]; then
    export GIT_COMMITTER_EMAIL="$NEW_EMAIL"
    export GIT_COMMITTER_NAME="$NEW_NAME"
fi
if [ "$GIT_AUTHOR_EMAIL" = "$OLD_EMAIL" ]; then
    export GIT_AUTHOR_EMAIL="$NEW_EMAIL"
    export GIT_AUTHOR_NAME="$NEW_NAME"
fi
' --tag-name-filter cat -- --branches --tags

git push --force origin main
```
