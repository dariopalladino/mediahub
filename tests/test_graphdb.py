"""
    Local-first media indexing and deduplication CLI.
    Copyright (C) 2026  Dario Palladino

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.

Tests for the graph DB builder."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlmodel import select

from mediactl.db.models import File, FileTag, Tag
from mediactl.db.session import get_session, init_db
from mediactl.graphdb.builder import build_from_scan, build_from_sqlite, write_incongruence_report
from mediactl.graphdb.models import GraphEdge, GraphNode
from mediactl.graphdb.session import get_graph_session, init_graph_db
from mediactl.scanner.local import LocalScanner


def _add_file(session, **overrides) -> File:
    defaults = dict(
        first_seen_at="2023-01-01T00:00:00+00:00",
        last_seen_at="2023-01-01T00:00:00+00:00",
        indexed_at="2023-01-01T00:00:00+00:00",
        created_at="2023-01-01T00:00:00+00:00",
        scan_status="indexed",
    )
    defaults.update(overrides)
    f = File(**defaults)
    session.add(f)
    session.commit()
    session.refresh(f)
    return f


@pytest.fixture
def index_db(tmp_path: Path) -> Path:
    db = tmp_path / "index.db"
    init_db(db)
    return db


@pytest.fixture
def graph_db(tmp_path: Path) -> Path:
    db = tmp_path / "graph.db"
    init_graph_db(db)
    return db


def test_build_from_sqlite_creates_expected_nodes_and_edges(index_db: Path, graph_db: Path) -> None:
    with get_session() as session:
        _add_file(
            session, path="/media/photos/photo1.jpg", filename="photo1.jpg", extension="jpg",
            size_bytes=1024, sha256="aaa",
        )
        _add_file(
            session, path="/media/videos/video.mp4", filename="video.mp4", extension="mp4",
            size_bytes=5000, sha256="bbb",
        )
        tag = Tag(name="vacation")
        session.add(tag)
        session.commit()
        session.refresh(tag)
        photo = session.exec(select(File).where(File.path == "/media/photos/photo1.jpg")).one()
        session.add(FileTag(file_id=photo.id, tag_id=tag.id))
        session.commit()

    with get_session() as index_session, get_graph_session() as graph_session:
        result = build_from_sqlite(index_session, graph_session, update=False)
        graph_session.commit()

    assert result.mode == "build"
    assert result.nodes_created > 0

    with get_graph_session() as graph_session:
        file_nodes = graph_session.exec(select(GraphNode).where(GraphNode.node_type == "file")).all()
        assert {n.key for n in file_nodes} == {"/media/photos/photo1.jpg", "/media/videos/video.mp4"}

        dir_nodes = graph_session.exec(select(GraphNode).where(GraphNode.node_type == "directory")).all()
        assert {n.key for n in dir_nodes} == {"/media", "/media/photos", "/media/videos"}

        tag_nodes = graph_session.exec(select(GraphNode).where(GraphNode.node_type == "tag")).all()
        assert {n.key for n in tag_nodes} == {"vacation"}

        type_nodes = graph_session.exec(select(GraphNode).where(GraphNode.node_type == "media_type")).all()
        assert {n.key for n in type_nodes} == {"Images", "Videos"}

        has_tag_edges = graph_session.exec(select(GraphEdge).where(GraphEdge.relation == "HAS_TAG")).all()
        assert len(has_tag_edges) == 1

        contains_edges = graph_session.exec(select(GraphEdge).where(GraphEdge.relation == "CONTAINS")).all()
        # /media->photos, /media->videos, photos->photo1.jpg, videos->video.mp4
        assert len(contains_edges) == 4


def test_build_from_sqlite_duplicate_group_edges(index_db: Path, graph_db: Path) -> None:
    with get_session() as session:
        canonical = _add_file(
            session, path="/media/a.jpg", filename="a.jpg", extension="jpg",
            size_bytes=100, sha256="shared", is_duplicate=0,
        )
        _add_file(
            session, path="/media/b.jpg", filename="b.jpg", extension="jpg",
            size_bytes=100, sha256="shared", is_duplicate=1, canonical_file_id=canonical.id,
        )

    with get_session() as index_session, get_graph_session() as graph_session:
        build_from_sqlite(index_session, graph_session, update=False)
        graph_session.commit()

    with get_graph_session() as graph_session:
        dup_edges = graph_session.exec(select(GraphEdge).where(GraphEdge.relation == "DUPLICATE_OF")).all()
        member_edges = graph_session.exec(select(GraphEdge).where(GraphEdge.relation == "MEMBER_OF")).all()
        assert len(dup_edges) == 1
        assert len(member_edges) == 1

        b_node = graph_session.exec(select(GraphNode).where(GraphNode.key == "/media/b.jpg")).one()
        a_node = graph_session.exec(select(GraphNode).where(GraphNode.key == "/media/a.jpg")).one()
        edge = dup_edges[0]
        assert edge.source_id == b_node.id
        assert edge.target_id == a_node.id


def test_update_from_sqlite_flags_incongruences(index_db: Path, graph_db: Path) -> None:
    with get_session() as session:
        _add_file(session, path="/media/keep.jpg", filename="keep.jpg", extension="jpg", size_bytes=100)
        stale = _add_file(session, path="/media/removed.jpg", filename="removed.jpg", extension="jpg", size_bytes=50)

    with get_session() as index_session, get_graph_session() as graph_session:
        build_from_sqlite(index_session, graph_session, update=False)
        graph_session.commit()

    # Simulate drift: DB changes after the graph was built.
    with get_session() as session:
        keep = session.exec(select(File).where(File.path == "/media/keep.jpg")).one()
        keep.size_bytes = 999
        session.add(keep)
        removed = session.exec(select(File).where(File.path == stale.path)).one()
        session.delete(removed)
        _add_file(session, path="/media/new.jpg", filename="new.jpg", extension="jpg", size_bytes=10)
        session.commit()

    with get_session() as index_session, get_graph_session() as graph_session:
        result = build_from_sqlite(index_session, graph_session, update=True)
        graph_session.commit()

    kinds = {(e.kind, e.key) for e in result.incongruences}
    assert ("updated", "/media/keep.jpg") in kinds
    assert ("removed", "/media/removed.jpg") in kinds
    assert ("added", "/media/new.jpg") in kinds
    # "added" is routine growth, not counted as an incongruence
    assert result.incongruences_count == 2

    # Property diffs are per-field, not a whole-blob JSON compare.
    updated_entry = next(e for e in result.incongruences if e.kind == "updated")
    assert updated_entry.field == "properties.size_bytes"
    assert updated_entry.old_value == "100"
    assert updated_entry.new_value == "999"

    with get_graph_session() as graph_session:
        remaining = {n.key for n in graph_session.exec(select(GraphNode).where(GraphNode.node_type == "file"))}
        assert remaining == {"/media/keep.jpg", "/media/new.jpg"}


def test_build_from_scan_creates_structural_nodes(tmp_path: Path, graph_db: Path) -> None:
    root = tmp_path / "root"
    (root / "sub").mkdir(parents=True)
    (root / "sub" / "a.txt").write_text("hello")
    (root / "b.jpg").write_bytes(b"\xff\xd8\xff")

    scanner = LocalScanner(exclude_patterns=[], max_depth=-1, workers=1)

    with get_graph_session() as graph_session:
        result = build_from_scan(scanner, str(root), graph_session, update=False)
        graph_session.commit()

    assert result.source == "scan"
    with get_graph_session() as graph_session:
        file_nodes = graph_session.exec(select(GraphNode).where(GraphNode.node_type == "file")).all()
        assert {n.label for n in file_nodes} == {"a.txt", "b.jpg"}
        # scan-source nodes carry no hash/tag data
        for n in file_nodes:
            props = json.loads(n.properties or "{}")
            assert "sha256" not in props


def test_write_incongruence_report_writes_json(index_db: Path, graph_db: Path, tmp_path: Path) -> None:
    with get_session() as session:
        _add_file(session, path="/media/one.jpg", filename="one.jpg", extension="jpg", size_bytes=1)

    with get_session() as index_session, get_graph_session() as graph_session:
        build_from_sqlite(index_session, graph_session, update=False)
        graph_session.commit()

    with get_session() as session:
        f = session.exec(select(File).where(File.path == "/media/one.jpg")).one()
        f.size_bytes = 2
        session.add(f)
        session.commit()

    with get_session() as index_session, get_graph_session() as graph_session:
        result = build_from_sqlite(index_session, graph_session, update=True)
        graph_session.commit()

    report_path = write_incongruence_report(result, graph_db)
    assert report_path.exists()

    payload = json.loads(report_path.read_text())
    assert payload["mode"] == "update"
    assert payload["source"] == "sqlite"
    assert payload["summary"]["incongruences_count"] == 1
    assert len(payload["incongruences"]) == 1

    latest = graph_db.parent / "graph_reports" / "graph_sqlite_update_latest.json"
    assert latest.exists()
