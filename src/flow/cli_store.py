"""``flow dict`` and ``flow snippet`` commands (manage the local database from the terminal)."""

from __future__ import annotations

import argparse
from pathlib import Path

from flow.store.db import Database, default_db_path
from flow.store.dictionary import DictionaryStore
from flow.store.snippets import SnippetStore


def add_parsers(sub) -> None:  # noqa: ANN001
    d = sub.add_parser("dict", help="manage the personal dictionary")
    d.add_argument("action", choices=["add", "list", "remove", "import", "export"])
    d.add_argument("arg", nargs="?", help="word, or file path for import/export")
    d.add_argument("--spoken", help="spoken form to replace with the word")
    d.add_argument("--star", action="store_true", help="priority word")
    s = sub.add_parser("snippet", help="manage snippets")
    s.add_argument("action", choices=["add", "list", "remove"])
    s.add_argument("trigger", nargs="?")
    s.add_argument("content", nargs="?")
    s.add_argument("--anywhere", action="store_true", help="also expand inside longer sentences")


def run(args: argparse.Namespace) -> int:
    db = Database(default_db_path())
    if args.cmd == "snippet":
        return _snippets(args, SnippetStore(db))
    return _dictionary(args, DictionaryStore(db))


def _snippets(args: argparse.Namespace, store: SnippetStore) -> int:
    if args.action == "add" and args.trigger and args.content:
        store.add(args.trigger, args.content, args.anywhere)
    elif args.action == "remove" and args.trigger:
        print("removed" if store.delete(args.trigger) else "not found")
    elif args.action == "list":
        for s in store.list():
            print(f"{s.trigger!r} -> {s.content!r}{' (anywhere)' if s.anywhere else ''}")
    return 0


def _dictionary(args: argparse.Namespace, d: DictionaryStore) -> int:
    if args.action == "add" and args.arg:
        d.add(args.arg, args.spoken, args.star)
    elif args.action == "remove" and args.arg:
        print("removed" if d.delete(args.arg) else "not found")
    elif args.action == "list":
        for e in d.list():
            spoken = f"  <- {e.spoken}" if e.spoken else ""
            print(f"{'*' if e.starred else ' '} {e.written}{spoken}")
    elif args.action == "import" and args.arg:
        ok, bad = d.import_text(Path(args.arg).read_text("utf-8"))
        print(f"imported {ok}, skipped {bad}")
    elif args.action == "export" and args.arg:
        text = d.export_json() if args.arg.endswith(".json") else d.export_csv()
        Path(args.arg).write_text(text, "utf-8-sig")
    return 0
