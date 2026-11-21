# Working agreements for agents

## Scope and ownership

- Treat the user's requested outcome and explicit constraints as the acceptance criteria. Read the repository instructions that apply to the paths you touch and inspect the relevant code, documentation, and tests before editing.
- Check the worktree before making changes. Preserve existing user changes, and keep edits focused on the requested outcome. Use reasonable, reversible assumptions to keep moving and surface meaningful assumptions when reporting the result.
- The primary agent owns the result through implementation, verification, review, and follow-up. Split independent work only where it helps, with clear ownership and a shared contract for changes that must integrate.
- Ask for input when an unresolved decision materially changes the scope or when a step requires authorization. Continue independent work while waiting.

## Implementation and verification

- Prefer the simplest change that satisfies the acceptance criteria. Follow local conventions and reuse existing logic where it fits. Preserve behavior that existing callers depend on unless the task requires a change.
- Work in coherent increments. Verify the normal user entry point and the failure or compatibility cases affected by the change. Use targeted tests first, then run broader checks when the change crosses boundaries or could cause wider regressions.
- Add a regression test when it covers a concrete failure that existing tests miss, or when the user or repository requires one. Inspect the final diff for accidental changes and record what was actually checked.
- Diagnose failed checks and retry or fix recoverable issues within scope. If a check stays unavailable, record the specific limitation and what remains unverified.

## Independent review at major checkpoints

A major checkpoint closes a meaningful piece of work, such as an architectural or contract decision that constrains later work, a working end-to-end milestone, a risky migration or integration, or the final deliverable. Routine intermediate edits can be reviewed together at the next checkpoint.

1. At each major checkpoint, have a separate agent that did not implement the work review the actual diff or artifact. Give the reviewer the task, acceptance criteria, relevant constraints, exact review scope, and checks already run. Ask for an independent assessment based on the evidence. The reviewer should inspect and report findings without editing the work under review.
2. Ask the reviewer to report findings in severity order. Each finding should name the affected file, line, or artifact when possible, explain the concrete impact, and say how to verify it. Ask for an explicit verdict even when there are no findings or when part of the work could not be verified.
3. Check each finding against the evidence. Fix blockers before advancing to dependent work. Resolve major findings within scope or get explicit user agreement to defer them. Address minor findings where the fix is useful and focused. Record the disposition of findings that remain open or are rejected, including the supporting evidence for each disputed blocker or major finding.
4. After fixing a blocker or major finding, rerun the affected checks and have an independent reviewer verify the fix. Before reporting completion, confirm that the latest substantive changes were covered by independent review. A checkpoint review can serve as the final review if it covers the delivered state.

| Severity | Meaning |
| --- | --- |
| **Blocker** | A required outcome is missing or unusable, a necessary check exposes a material failure, or proceeding would risk serious harm such as data loss, a security failure, or a critical regression. |
| **Major** | A material correctness, reliability, compatibility, or verification gap that warrants a fix before delivery. |
| **Minor** | A localized issue with limited impact that can be weighed against the scope of the task. |
| **Suggestion** | An optional improvement with no material effect on acceptance. |

## Completion

- Report completion only when the requested outcome is delivered, the applicable verification and independent review are complete, and every blocker is resolved. The primary agent must keep working on unresolved blockers while authorized steps can still make progress.
- If an external dependency, missing authorization, or unavailable independent reviewer makes further progress impossible, report the task as blocked or pending. State what is complete, what remains, the specific impediment, and what is needed to proceed.
- In the final handoff, summarize the outcome, checks run, independent review result, and any material assumptions, agreed deferrals, or verification gaps.
