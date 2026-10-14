# AGENTS.md

Guidance for AI agents (and humans) working in this repository.

## Project

AI-Driven Avatar-Based VR Digital Twin for Predictive Maintenance & Fault Visualization of Wind
Turbines. Unity 6000.6 LTS client (URP / Metal, OpenXR + XR Interaction Toolkit) with a Python
FastAPI service for telemetry simulation and explainable health scoring. See
[`README.md`](README.md) and [`docs/PRD.md`](docs/PRD.md).

## Repository layout

| Path | Purpose |
| --- | --- |
| `Assets/` | Unity assets, scenes, scripts, settings (URP assets) |
| `Packages/manifest.json` | UPM dependency manifest (pinned versions) |
| `ProjectSettings/` | Unity project settings (versioned) |
| `docs/` | Product/design documentation |
| `tools/` (planned) | Python telemetry simulation & scoring service |

## Unity conventions

- Editor version: **6000.6.5f1**. Never hand-edit `ProjectSettings/ProjectVersion.txt` or
  `Library/`.
- `Library/`, `Temp/`, `Logs/`, `UserSettings/`, `*.csproj`, `*.sln`, `*.slnx` are generated and
  git-ignored — do not commit them.
- New UPM packages are added by editing `Packages/manifest.json`; commit the regenerated
  `Packages/packages-lock.json` alongside it.
- Scripts live in `Assets/Scripts/<Feature>/`; keep editor-only code in an `Editor/` folder.
- Follow the existing C# style (4-space indent, file-scoped namespaces, PascalCase types).

## GitHub Workflow

Applies when the user asks to push code to GitHub.

1. **Never push directly to `main`**, even when explicitly asked.
2. Create a descriptive `feature/` or `fix/` branch for the finalized changes.
3. Fetch the latest `main` and confirm the branch is conflict-free before opening a PR.
   ```bash
   git fetch origin
   git rebase origin/main   # resolve conflicts locally, never push force without asking
   ```
4. Commit using **Conventional Commits**: `<type>(<scope>): <description>`, e.g.
   `feat(backend): add user authentication`, `fix(frontend): resolve login validation issue`,
   `docs(redis): document cache TTLs`. Allowed types: `feat`, `fix`, `docs`, `refactor`, `test`,
   `chore`, `build`, `ci`, `perf`, `style`.
5. Push the branch, then open a PR into `main`.
   ```bash
   git push -u origin <branch>
   gh pr create --base main --head <branch> --title "release(<scope>): <description>" --body "$(cat <<'EOF'
   ## Summary
   - ...

   ## Changes
   - ...

   ## Verification
   - ...
   EOF
   )"
   ```
6. **PR title must be `release(<scope>): <description>`** with a free-form scope
   (`backend`, `sdk`, `ci`, `visual`, …).
7. **PR body must not be empty.** Both are enforced by the PR Hygiene workflow and will fail CI
   otherwise.

### Checklist before pushing

- [ ] Working tree is clean and staged files are only intended changes
- [ ] No secrets, credentials, `.env` files, or `Library/` content staged
- [ ] `git status`, `git diff`, and `git log --oneline -10` reviewed
- [ ] Branch is rebased on `origin/main`
- [ ] Commit message follows Conventional Commits
- [ ] PR title is `release(<scope>): <description>` and body is non-empty