import * as vscode from "vscode";
import type { ReviewStore } from "./reviewStore";
import type { Change } from "./types";

/**
 * Tree view for the "Turns" panel. Pure navigation/overview — clicking a
 * turn or change opens the review webview (ReviewPanel), which is where
 * approve/reject/revert actually happen. Keeping the tree read-only avoids
 * duplicating decision logic in two UI surfaces (the brief is explicit that
 * the UI must not own business logic, and that includes not having two
 * different UI components independently reach into the store).
 */
export class TurnsTreeProvider implements vscode.TreeDataProvider<TreeNode> {
  private readonly onDidChangeTreeDataEmitter = new vscode.EventEmitter<TreeNode | undefined>();
  readonly onDidChangeTreeData = this.onDidChangeTreeDataEmitter.event;

  private connected = false;

  constructor(private readonly store: ReviewStore | undefined) {}

  setConnected(connected: boolean): void {
    this.connected = connected;
    this.refresh();
  }

  refresh(): void {
    this.onDidChangeTreeDataEmitter.fire(undefined);
  }

  getTreeItem(element: TreeNode): vscode.TreeItem {
    return element.toTreeItem();
  }

  getChildren(element?: TreeNode): TreeNode[] {
    if (element) return element.children();

    if (!this.connected || !this.store) {
      return [new MessageNode("Not connected — run “SuperDocs Review: Connect Account”")];
    }

    const changes = this.store.listAllChanges();
    if (changes.length === 0) {
      return [new MessageNode("Connected. No agent turns observed yet.")];
    }

    const byTurn = new Map<string, Change[]>();
    for (const c of changes) {
      const list = byTurn.get(c.turnId) ?? [];
      list.push(c);
      byTurn.set(c.turnId, list);
    }

    return [...byTurn.entries()]
      .sort((a, b) => b[0].localeCompare(a[0]))
      .map(([turnId, turnChanges]) => new TurnNode(turnId, turnChanges));
  }
}

interface TreeNode {
  toTreeItem(): vscode.TreeItem;
  children(): TreeNode[];
}

class MessageNode implements TreeNode {
  constructor(private readonly label: string) {}
  toTreeItem(): vscode.TreeItem {
    return new vscode.TreeItem(this.label, vscode.TreeItemCollapsibleState.None);
  }
  children(): TreeNode[] {
    return [];
  }
}

const STATUS_ICON: Record<Change["status"], string> = {
  proposed: "circle-outline",
  approved: "check",
  rejected: "close",
  reverted: "discard",
  conflicted: "warning",
  failed: "error",
  superseded: "history",
};

class TurnNode implements TreeNode {
  constructor(
    private readonly turnId: string,
    private readonly changes: Change[]
  ) {}

  toTreeItem(): vscode.TreeItem {
    const pending = this.changes.filter((c) => c.status === "proposed").length;
    const conflicts = this.changes.filter((c) => c.status === "conflicted").length;
    const parts = [`${this.changes.length} change${this.changes.length === 1 ? "" : "s"}`];
    if (pending > 0) parts.push(`${pending} pending`);
    if (conflicts > 0) parts.push(`${conflicts} conflict${conflicts === 1 ? "" : "s"}`);

    const item = new vscode.TreeItem(`Turn ${this.turnId}`, vscode.TreeItemCollapsibleState.Collapsed);
    item.description = parts.join(", ");
    item.iconPath = new vscode.ThemeIcon(conflicts > 0 ? "warning" : pending > 0 ? "circle-outline" : "check-all");
    item.command = { command: "superdocsAgentReview.openPanel", title: "Open SuperDocs Review" };
    return item;
  }

  children(): TreeNode[] {
    return this.changes.map((c) => new ChangeNode(c));
  }
}

class ChangeNode implements TreeNode {
  constructor(private readonly change: Change) {}

  toTreeItem(): vscode.TreeItem {
    const label = `${this.change.operation} · ${this.change.chunkId ?? "(new)"}`;
    const item = new vscode.TreeItem(label, vscode.TreeItemCollapsibleState.None);
    item.description = this.change.status;
    item.iconPath = new vscode.ThemeIcon(STATUS_ICON[this.change.status]);
    if (this.change.reconciliation === "claimed_not_observed") {
      item.description = `⚠ claimed but not observed`;
    }
    item.command = { command: "superdocsAgentReview.openPanel", title: "Open SuperDocs Review" };
    return item;
  }

  children(): TreeNode[] {
    return [];
  }
}
