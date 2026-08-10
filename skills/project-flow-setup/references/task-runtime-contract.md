# DevConductor Task Runtime Contract

This file contains stable execution rules so the controller can reference one versioned contract instead of repeating it in every user turn.

## Sources of truth

- Treat the approved Plan, current repository files, Git state, AGENTS.md, Project Profile facts, and configured stage Skills as authoritative.
- Task memory is a reusable context index, not permission to broaden scope. If it conflicts with current files or Git, current facts win.
- Read only the smallest relevant code, Plan sections, direct definitions, and direct call sites required for the current round.

## Write and Git boundaries

- Keep changes inside the bound Worktree and the requirement owner unless the approved Plan explicitly says otherwise.
- Never Commit, Push, Merge, create/delete Worktrees, or change Git configuration during execution or repair rounds.
- `changed_files` must contain only files actually written in the current round. Do not re-report unrelated pre-existing Worktree changes.
- Preserve already accepted implementation, documentation, and tests unless the current feedback directly requires a change.

## Verification evidence

- Run only relevant automated checks that are safe in the current environment and report their real result.
- Never mark compilation, Self Check, Play Mode, editor, device, or live-service verification as passed unless it actually ran successfully.
- Prefer existing Self Checks, debug panels, and diagnostic logs. Add logs only inside the requirement owner when essential; keep them low-frequency, searchable, and restricted to Editor/Development builds where appropriate.

## Full execution acceptance output

- Provide a 3–5 minute minimum manual verification path with 2–5 concrete steps.
- Provide 3–6 detailed manual cases using P0/P1/P2. Set P0 cases to `required=true`; optional regression coverage may be false.
- Each step and case must state the action, observable result, precise log filters, expected logs, and failure signals.
- `acceptance_logs` must use the verification sources configured by the Project Profile.

## Targeted repair output

- For acceptance fixes and post-Commit Bug fixes, address only the new feedback, listed Review findings, affected files, and direct regressions.
- Return only 1–4 verification items affected by the current repair; DevConductor merges them with the previously accepted baseline.
- Mark checks that did not run as `skipped`, never `passed`.

## Fast mode

- Fast mode reuses the task's persistent Codex App Thread and does not launch a second independent Review.
- Inspect the current round Diff and run the smallest directly relevant checks before returning the structured result.

## Knowledge candidates

- Knowledge extraction is a read-only post-Commit stage. It may inspect the task-memory reference, Plan reference and Hash, current code, Commit, tests, Review, and manual acceptance evidence, but must not modify or publish any project file, Skill, automation, task state, or Git state.
- Return zero to five candidates. Allowed types are stable fact, decision, runbook, pitfall, acceptance rule, Skill candidate, and automation candidate.
- Keep only knowledge that is likely to help a future task. Exclude one-off task narration, full chat summaries, obvious change lists, duplicated project knowledge, and unsupported guesses.
- Use project scope by default. Use global-candidate only when the evidence supports reuse across projects.
- Every candidate must name its applicability, non-scope, suggested publication target, novelty, and up to eight direct evidence references from a Commit, file, test, Review, or manual acceptance result.
- If no candidate clears this bar, return an empty candidate array and state that the task needs no knowledge extraction.
- Candidate approval or ignore status is review metadata stored only in DevConductor runtime. Approval is not permission to edit the suggested target.
