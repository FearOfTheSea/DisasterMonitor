"""Attach durable acquisition descendants to every viewer of their parent."""

import sqlite3


def attach_collection_descendants(db: sqlite3.Connection, scan: str, key: str) -> None:
    db.execute(
        "WITH RECURSIVE children(id) AS (SELECT ? UNION SELECT child FROM "
        "work_links JOIN children ON parent=children.id) INSERT OR IGNORE "
        "INTO scan_work SELECT ?,id FROM children",
        (key, scan),
    )


def link_collection_work(db: sqlite3.Connection, parent: str, child: str) -> None:
    db.execute("INSERT OR IGNORE INTO work_links VALUES(?,?)", (parent, child))
    db.execute(
        "WITH RECURSIVE descendants(id) AS (SELECT ? UNION "
        "SELECT child FROM work_links JOIN descendants ON parent=descendants.id) "
        "INSERT OR IGNORE INTO scan_work SELECT s.scan,d.id FROM scan_work s "
        "CROSS JOIN descendants d WHERE s.work=?",
        (child, parent),
    )
