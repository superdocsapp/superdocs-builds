# Demo guide

## Fastest path

PowerShell:

```powershell
cd <this-folder>
.\run-demo.ps1
```

Open `http://localhost:8031`.

The browser demo is dependency-free and exists so the interaction/evidence flow can be reviewed immediately. The `src/` folder contains the VS Code extension implementation; `package.json` declares the extension command and DOCX export dependency. Open that folder and press **F5** to run the panel.

## 45-second evidence sequence

1. Start on **Renewal notice** (Turn 18 group) and capture the full three-pane workspace.
2. Click **Approve & continue**. Select that item again — **Revert** is now visible.
3. Click **Revert** and confirm only the renewal-notice item returns to its original working artifact.
4. Approve **Support escalation**, then on **Payment terms** capture the **Mismatch** inspector and click **Reject**.
5. Select the Turn 7 **Claude Code** item and capture the false-claim / no-artifact-change diff.
6. Click **Export evidence** and save the JSON.
7. Capture the queue showing approved, rejected, and reverted states.

Revert is shown only after a change is approved or applied. It is hidden for pending, rejected, and already-reverted items. The change queue can also be moved with Arrow Up / Arrow Down when a queue row is focused.
