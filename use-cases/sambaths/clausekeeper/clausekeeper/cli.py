import argparse
import json
import os
import sys

from . import db, discover, editing, ingest, linking, packing, rechecking
from .library import LIBRARY_PATH, load_library, sample_ids, subset
from .superdocs import FixtureTransport, HttpTransport, OpsFloorExceeded, SuperDocsClient


def build_client(args):
    fixture = getattr(args, "fixture", None) or os.environ.get("CK_FIXTURE")
    if fixture:
        os.environ.setdefault("CK_DETERMINISTIC_NOW", "2026-08-23T00:00:00Z")
    transport = FixtureTransport(fixture) if fixture else HttpTransport()
    return SuperDocsClient(transport)


def sync_clauses(conn, clauses):
    for c in clauses:
        conn.execute(
            "INSERT INTO clauses(clause_id, title, expectation, level,"
            " linkable) VALUES(?,?,?,?,?) ON CONFLICT(clause_id) DO UPDATE"
            " SET title = excluded.title, expectation = excluded.expectation",
            (c["id"], c["title"], c["expectation"], c["level"],
             int(c["linkable"])))
    conn.commit()


def cmd_init(args):
    conn = db.connect(args.db)
    client = build_client(args)
    try:
        result = ingest.init_session(client, conn, args.corpus)
        sync_clauses(conn, load_library(args.library))
        print(f"session {result['session_id']}: {result['documents']} documents"
              f" bound ({result['unbound']} without durable id)")
    finally:
        conn.close()


def cmd_link(args):
    conn = db.connect(args.db)
    client = build_client(args)
    try:
        clauses = subset(load_library(args.library), args.sample)
        if getattr(args, "plan", False):
            _print_link_plan(client, conn, clauses, args)
            return
        discovery = None
        if getattr(args, "discover", False):
            discovery = discover.run_discover(client, conn, clauses)
        results = linking.build_links(client, conn, clauses)
        persist_usage(conn, client)
        mapping_ops = sum(r["ops_charged"] for r in results)
        total_ops = mapping_ops + (discovery or {}).get("ops_charged", 0)
        for r in results:
            print(f"linked {r['doc']}: {r['links_added']} clauses covered")
        if discovery is None:
            print(f"ops charged this run: {total_ops}")
        elif discovery["ops_charged"]:
            print(f"ops charged this run: {total_ops} (mapping"
                  f" {mapping_ops} + discover search"
                  f" {discovery['ops_charged']})")
        else:
            print(f"ops charged this run: {total_ops} (mapping only)")
        expected = args.corpus_expected
        if expected:
            for u in linking.audit_against_expected(conn, expected):
                state = "DETECTED" if u["detected"] else "MISSED"
                print(f"seed {u['seed']} clause {u['clause_id']}: {state}")
    except OpsFloorExceeded as exc:
        print(f"STOPPED: {exc}")
        sys.exit(2)
    finally:
        conn.close()


def _print_link_plan(client, conn, clauses, args):
    if getattr(args, "discover", False):
        discover.plan_discover(client, conn, clauses)
        return
    docs = discover.bound_documents(conn)
    print("LINK PLAN (preview mode - zero billable ops)")
    print(f"  {len(docs)} documents × 1 verification turn each"
          f" = ~{len(docs)} ops (unchanged by --plan)")
    print("  add --discover for +≤1 op shortlisting pass")


def cmd_edit(args):
    conn = db.connect(args.db)
    client = build_client(args)
    try:
        summary = editing.guided_edit(client, conn, args.document,
                                      args.instruction)
        persist_usage(conn, client)
        print(json.dumps(summary, indent=2))
    except OpsFloorExceeded as exc:
        print(f"STOPPED: {exc}")
        sys.exit(2)
    finally:
        conn.close()


def cmd_recheck(args):
    conn = db.connect(args.db)
    client = build_client(args)
    try:
        scope = None
        if getattr(args, "sample", None):
            scope = [c["id"] for c in
                     subset(load_library(args.library), args.sample)]
        if args.plan:
            detection = rechecking.detect_changed(client, conn)
            plan = rechecking.build_plan(client, conn, detection,
                                         scope_clauses=scope)
            print("RECHECK PLAN (preview mode - zero billable ops)")
            for item in plan["items"]:
                names = ", ".join(item["clauses"]) or "(none)"
                print(f"  {item['name']}: {len(item['clauses'])} affected"
                      f" clauses [{names}] ~{item['estimated_ops']} op")
            print(f"estimated cost: {plan['estimated_ops']} ops;"
                  f" spent so far: 0")
            if plan["skips"]:
                print(f"skipped (already checked): {plan['skips']}")
            return
        summary = rechecking.run_recheck(client, conn, scope_clauses=scope)
        persist_usage(conn, client)
        print(json.dumps(summary, indent=2))
        print(f"total ops this run: {summary['ops_spent']}")
    except OpsFloorExceeded as exc:
        print(f"STOPPED: {exc}")
        sys.exit(2)
    finally:
        conn.close()


def cmd_pack(args):
    conn = db.connect(args.db)
    client = build_client(args)
    try:
        summary = packing.build_pack(
            client, conn, template_path=args.template, out_dir=args.out,
            filename=args.filename, library_path=args.library)
        persist_usage(conn, client)
        print(json.dumps(summary, indent=2))
    except (OpsFloorExceeded, packing.LanguageRailError) as exc:
        print(f"STOPPED: {exc}")
        sys.exit(2)
    finally:
        conn.close()


def cmd_show(args):
    conn = db.connect(args.db)
    try:
        rows = conn.execute(
            "SELECT l.clause_id, c.title, d.name AS doc, l.heading_path,"
            " l.quote_excerpt, l.status, l.last_verified_at FROM links l JOIN"
            " clauses c ON c.clause_id = l.clause_id JOIN documents d ON"
            " d.durable_document_id = l.durable_document_id ORDER BY"
            " l.clause_id").fetchall()
        print(f"{'CLAUSE':<7} {'STATUS':<8} {'DOCUMENT':<34} SECTION")
        for r in rows:
            quote = f" — {r['quote_excerpt'][:60]}…" if args.verbose else ""
            print(f"{r['clause_id']:<7} {r['status']:<8} {r['doc']:<34}"
                  f" {r['heading_path'][:44]}{quote}")

        linked = {r["clause_id"] for r in conn.execute(
            "SELECT DISTINCT clause_id FROM links")}
        uncovered = [c for c in load_library(args.library)
                     if c["linkable"] and c["id"] not in linked]
        if uncovered:
            print("\nUNCOVERED CLAUSES (no evidence anywhere):")
            for c in uncovered:
                print(f"  {c['id']} {c['title']}")
        gaps = conn.execute(
            "SELECT g.narrative, g.detected_at FROM gaps g WHERE"
            " g.gap_id IN (SELECT MAX(gap_id) FROM gaps GROUP BY clause_id,"
            " durable_document_id) ORDER BY g.detected_at DESC").fetchall()
        if gaps:
            print("\nOPEN GAPS:")
            for g in gaps:
                print(f"  [{g['detected_at']}] {g['narrative']}")
        usage = conn_usage(args.db)
        if usage:
            print(f"\nusage: {usage['ops']} billable ops logged;"
                  f" lowest monthly_remaining seen: {usage['min_remaining']}")
    finally:
        conn.close()


def conn_usage(db_path):
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT SUM(ops_charged) ops, MIN(monthly_remaining) min_remaining"
        " FROM usage_log").fetchone()
    conn.close()
    return {"ops": row["ops"] or 0, "min_remaining": row["min_remaining"]}


def persist_usage(conn, client):
    for u in client.usage_log:
        conn.execute(
            "INSERT INTO usage_log(ts, call, job_id, ops_charged, was_billable,"
            " monthly_used, monthly_remaining, quota_exhausted) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (u["ts"], u["call"], u["job_id"], u["ops_charged"],
             int(u["was_billable"]), u["monthly_used"], u["monthly_remaining"],
             int(u["quota_exhausted"])))
    conn.commit()


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="clausekeeper",
        description="ISO 9001 traceability matrix over a SuperDocs session")
    parser.add_argument("--db", default="clausekeeper.db")
    parser.add_argument("--library", default=str(LIBRARY_PATH))
    parser.add_argument(
        "--corpus", default=str(LIBRARY_PATH.parent.parent / "corpus/northgate"))
    parser.add_argument(
        "--corpus-expected",
        default=str(LIBRARY_PATH.parent.parent /
                    "corpus/northgate/expected-gaps.yaml"),
        help="expected-gaps manifest for seed audit")
    parser.add_argument("--fixture", default=None,
                        help="replay recorded API responses instead of live"
                             " calls (keyless)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="bootstrap a multi-document session")
    p.add_argument("--corpus",
                   default=str(LIBRARY_PATH.parent.parent / "corpus/northgate"))
    p.add_argument("--sample", type=int, default=None)

    p = sub.add_parser("link", help="build the clause-to-section matrix")
    p.add_argument("--sample", type=int, default=None)
    p.add_argument("--discover", action="store_true",
                   help="opt-in evidence-discovery pass before mapping"
                        " (shortlists candidate sections, ~+1 op max)")
    p.add_argument("--plan", action="store_true",
                   help="zero-spend preview of the mapping pass")

    p = sub.add_parser("edit", help="guided edit through the approve flow")
    p.add_argument("document")
    p.add_argument("--instruction", required=True)

    p = sub.add_parser("recheck", help="detect changes and verify coverage")
    p.add_argument("--plan", action="store_true",
                   help="zero-spend preview of the re-check cycle")
    p.add_argument("--sample", type=int, default=None)

    p = sub.add_parser("show", help="print the matrix and open gaps")
    p.add_argument("--verbose", action="store_true")

    p = sub.add_parser(
        "pack",
        help="generate the branded audit-readiness pack and export it")
    p.add_argument("--template",
                   help="letterhead DOCX to upload once (reused after)")
    p.add_argument("--out", default="exports",
                   help="directory for exported files")
    p.add_argument("--filename", default="northgate-audit-readiness-pack")

    p = sub.add_parser("sample-ids", help="list the demo sample subset")
    p.set_defaults(func=lambda a: print("\n".join(sample_ids(a.library))))

    args = parser.parse_args(argv)
    if getattr(args, "func", None):
        args.func(args)
        return
    {"init": cmd_init, "link": cmd_link, "edit": cmd_edit,
     "recheck": cmd_recheck, "show": cmd_show,
     "pack": cmd_pack}[args.command](args)


if __name__ == "__main__":
    main()
