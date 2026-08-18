# GitHub manual steps

GitHub CLI/authentication was unavailable in the verification environment, and the configured `origin` is the official upstream. Do not push there directly.

1. Fork the official `superdocs-builds` repository in GitHub.
2. From the local public repository, add the fork: `git remote add fork https://github.com/<your-user>/superdocs-builds.git`.
3. Push the prepared branch: `git push -u fork feat/payment-plan-agreement`.
4. Open a pull request from the fork branch to the official default branch.
5. Use title `feat(use-cases): add payment plan agreement builder` and paste `payment-plan-agreement/docs/submission/pr-description.md` as the description.
6. Confirm the public PR contains only the candidate folder and no Task 1/private-repository files.
