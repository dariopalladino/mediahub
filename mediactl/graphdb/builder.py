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

Graph build/update logic.

Two sources:
- "sqlite": derive nodes/edges from the already-indexed mediactl DB (files, tags,
  duplicate groups). Fast, and reflects hashes/tags/dup-detection already computed
  by `scan`/`dedupe`.
- "scan": walk the root directory (local or SMB) fresh, independent of the index DB.
  Produces structural nodes only (file/directory/media_type) — no hashes or tags.

Two modes:
- build (update=False): wipe and recreate the graph DB from the source.
- update (update=True): incrementally sync an existing graph DB against the source,
  and record every drift found (new/changed/orphaned nodes) as an "incongruence" —
  i.e. a place where the graph and the source had gotten out of sync before this run.

Directory/media_type/tag/duplicate_group nodes are structural scaffolding and are
never reported as incongruences — only `file` nodes are, since the file is the
single source of truth being mirrored from `sqlite`/`scan` into the graph.
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import structlog
from sqlmodel import Session, delete, select

from mediactl.db.models import File, FileTag, Tag
from mediactl.graphdb.models import GraphEdge, GraphNode
from mediactl.moc import _ext_to_type
from mediactl.scanner.base import BaseScanner

log = structlog.get_logger()

_NodeCache = dict[tuple[str, str], GraphNode]
_EdgeCache = set[tuple[int, int, str]]


@dataclass
class IncongruenceEntry:
    """A single drift found between the graph and its source during an update."""

    kind: str  # "added" | "updated" | "removed"
    node_type: str
    key: str
    field: str | None = None
    old_value: str | None = None
    new_value: str | None = None


@dataclass
class GraphBuildResult:
    mode: str  # "build" | "update"
    source: str  # "sqlite" | "scan"
    nodes_created: int = 0
    nodes_updated: int = 0
    nodes_removed: int = 0
    edges_created: int = 0
    edges_removed: int = 0
    incongruences: list[IncongruenceEntry] = field(default_factory=list)

    @property
    def incongruences_count(self) -> int:
        """Drift entries only — 'added' is routine growth, not divergence."""
        return sum(1 for e in self.incongruences if e.kind in ("updated", "removed"))


def _now() -> str:
    return datetime.now(tz=UTC).isoformat()


def _dump(props: dict) -> str:
    return json.dumps(props, sort_keys=True, default=str)


def _short(value: str | None, limit: int = 200) -> str | None:
    if value is None:
        return None
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _load_props(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        loaded = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _diff_properties(old_raw: str | None, new_props: dict) -> list[tuple[str, str | None, str | None]]:
    """Per-key diff so incongruence reports say e.g. 'md5: a1b2... -> c3d4...'
    instead of a whole-blob JSON compare that an agent would have to re-diff itself.
    """
    old_props = _load_props(old_raw)
    changed: list[tuple[str, str | None, str | None]] = []
    for key in sorted(set(old_props) | set(new_props)):
        old_v = old_props.get(key)
        new_v = new_props.get(key)
        if old_v != new_v:
            old_s = _short(str(old_v)) if old_v is not None else None
            new_s = _short(str(new_v)) if new_v is not None else None
            changed.append((f"properties.{key}", old_s, new_s))
    return changed


def _wipe_graph(graph_session: Session) -> None:
    graph_session.exec(delete(GraphEdge))
    graph_session.exec(delete(GraphNode))
    graph_session.flush()


def _load_node_cache(graph_session: Session) -> _NodeCache:
    nodes = graph_session.exec(select(GraphNode)).all()
    return {(n.node_type, n.key): n for n in nodes}


def _load_edge_cache(graph_session: Session) -> _EdgeCache:
    edges = graph_session.exec(select(GraphEdge)).all()
    return {(e.source_id, e.target_id, e.relation) for e in edges}


def _upsert_node(
    graph_session: Session,
    cache: _NodeCache,
    result: GraphBuildResult,
    *,
    node_type: str,
    key: str,
    label: str,
    properties: dict,
    track_incongruence: bool,
) -> GraphNode:
    now = _now()
    new_props = _dump(properties)
    existing = cache.get((node_type, key))

    if existing is None:
        node = GraphNode(
            node_type=node_type, key=key, label=label,
            properties=new_props, created_at=now, updated_at=now,
        )
        graph_session.add(node)
        graph_session.flush()
        cache[(node_type, key)] = node
        result.nodes_created += 1
        if track_incongruence:
            result.incongruences.append(IncongruenceEntry(kind="added", node_type=node_type, key=key))
        return node

    changed_fields: list[tuple[str, str | None, str | None]] = []
    if existing.label != label:
        changed_fields.append(("label", existing.label, label))
    if existing.properties != new_props:
        changed_fields.extend(_diff_properties(existing.properties, properties))

    if changed_fields:
        existing.label = label
        existing.properties = new_props
        existing.updated_at = now
        graph_session.add(existing)
        result.nodes_updated += 1
        if track_incongruence:
            for field_name, old, new in changed_fields:
                result.incongruences.append(
                    IncongruenceEntry(
                        kind="updated", node_type=node_type, key=key,
                        field=field_name, old_value=_short(old), new_value=_short(new),
                    )
                )
    return existing


def _upsert_edge(
    graph_session: Session,
    edge_cache: _EdgeCache,
    result: GraphBuildResult,
    *,
    source_id: int,
    target_id: int,
    relation: str,
) -> None:
    triple = (source_id, target_id, relation)
    if triple in edge_cache:
        return
    graph_session.add(GraphEdge(source_id=source_id, target_id=target_id, relation=relation, created_at=_now()))
    edge_cache.add(triple)
    result.edges_created += 1


def _split_ancestors(path: str) -> list[str]:
    """Return ancestor directory keys for `path`, root-first, nearest-parent last.

    Local paths are absolute POSIX-style strings (scanner always resolves them).
    SMB paths are `smb://host/share/...` URIs; the share root is the topmost ancestor.
    """
    if path.startswith("smb://"):
        from mediactl.scanner.smb import parse_smb_uri

        host, share, subpath = parse_smb_uri(path)
        root = f"smb://{host}/{share}"
        dir_parts = [p for p in subpath.split("/") if p][:-1]
        ancestors = [root]
        accum = root
        for part in dir_parts:
            accum = f"{accum}/{part}"
            ancestors.append(accum)
        return ancestors

    dir_parts = [p for p in path.split("/") if p][:-1]
    ancestors = []
    accum = ""
    for part in dir_parts:
        accum = f"{accum}/{part}"
        ancestors.append(accum)
    return ancestors


def _link_directory_chain(
    graph_session: Session,
    node_cache: _NodeCache,
    edge_cache: _EdgeCache,
    result: GraphBuildResult,
    path: str,
    file_node: GraphNode,
) -> None:
    prev_node: GraphNode | None = None
    for anc_path in _split_ancestors(path):
        label = anc_path.rsplit("/", 1)[-1] or anc_path
        dir_node = _upsert_node(
            graph_session, node_cache, result,
            node_type="directory", key=anc_path, label=label,
            properties={"path": anc_path}, track_incongruence=False,
        )
        if prev_node is not None and prev_node.id is not None and dir_node.id is not None:
            _upsert_edge(
                graph_session, edge_cache, result,
                source_id=prev_node.id, target_id=dir_node.id, relation="CONTAINS",
            )
        prev_node = dir_node

    if prev_node is not None and prev_node.id is not None and file_node.id is not None:
        _upsert_edge(
            graph_session, edge_cache, result,
            source_id=prev_node.id, target_id=file_node.id, relation="CONTAINS",
        )


def _link_media_type(
    graph_session: Session,
    node_cache: _NodeCache,
    edge_cache: _EdgeCache,
    result: GraphBuildResult,
    file_node: GraphNode,
    extension: str,
) -> None:
    media_type = _ext_to_type(extension)
    type_node = _upsert_node(
        graph_session, node_cache, result,
        node_type="media_type", key=media_type, label=media_type,
        properties={}, track_incongruence=False,
    )
    if file_node.id is not None and type_node.id is not None:
        _upsert_edge(
            graph_session, edge_cache, result,
            source_id=file_node.id, target_id=type_node.id, relation="HAS_TYPE",
        )


def _prune_stale_tag_edges(
    graph_session: Session,
    result: GraphBuildResult,
    node_cache: _NodeCache,
    file_node: GraphNode,
    current_tag_names: set[str],
) -> None:
    if file_node.id is None:
        return
    existing_edges = graph_session.exec(
        select(GraphEdge).where(GraphEdge.source_id == file_node.id, GraphEdge.relation == "HAS_TAG")
    ).all()
    id_to_tag = {n.id: key for (ntype, key), n in node_cache.items() if ntype == "tag"}
    for edge in existing_edges:
        tag_name = id_to_tag.get(edge.target_id)
        if tag_name is not None and tag_name not in current_tag_names:
            graph_session.delete(edge)
            result.edges_removed += 1
            result.incongruences.append(
                IncongruenceEntry(
                    kind="updated", node_type="file", key=file_node.key,
                    field="tags", old_value=tag_name, new_value=None,
                )
            )


def _detect_removed_nodes(
    graph_session: Session,
    result: GraphBuildResult,
    *,
    node_type: str,
    current_keys: set[str],
) -> None:
    """Delete graph nodes of `node_type` whose key no longer exists in the source,
    and flag each as a 'removed' incongruence — the graph knew about something the
    source no longer does.
    """
    stale = list(graph_session.exec(select(GraphNode).where(GraphNode.node_type == node_type)))
    stale_ids = {n.id for n in stale if n.key not in current_keys and n.id is not None}
    if not stale_ids:
        return

    edges = graph_session.exec(
        select(GraphEdge).where(
            GraphEdge.source_id.in_(stale_ids) | GraphEdge.target_id.in_(stale_ids)  # type: ignore[attr-defined]
        )
    ).all()
    for edge in edges:
        graph_session.delete(edge)
        result.edges_removed += 1

    for node in stale:
        if node.id in stale_ids:
            graph_session.delete(node)
            result.nodes_removed += 1
            result.incongruences.append(IncongruenceEntry(kind="removed", node_type=node_type, key=node.key))

    graph_session.flush()


def build_from_sqlite(index_session: Session, graph_session: Session, *, update: bool) -> GraphBuildResult:
    """Build or incrementally update the graph DB from the main mediactl index DB."""
    result = GraphBuildResult(mode="update" if update else "build", source="sqlite")

    if not update:
        _wipe_graph(graph_session)

    node_cache = _load_node_cache(graph_session)
    edge_cache = _load_edge_cache(graph_session)

    files = list(index_session.exec(select(File)).all())
    by_id = {f.id: f for f in files if f.id is not None}

    tag_rows = index_session.exec(
        select(FileTag.file_id, Tag.name).join(Tag, Tag.id == FileTag.tag_id)  # type: ignore[arg-type]
    ).all()
    tags_by_file: dict[int, set[str]] = defaultdict(set)
    for file_id, tag_name in tag_rows:
        tags_by_file[file_id].add(tag_name)

    seen_paths: set[str] = set()

    # Pass 1: file/directory/media_type/tag nodes — every file node must exist
    # before pass 2 can wire up DUPLICATE_OF edges between them.
    for f in files:
        seen_paths.add(f.path)
        properties = {
            "filename": f.filename,
            "extension": f.extension,
            "size_bytes": f.size_bytes,
            "mime_type": f.mime_type,
            "md5": f.md5,
            "sha256": f.sha256,
            "is_duplicate": bool(f.is_duplicate),
            "created_at": f.created_at,
            "modified_at": f.modified_at,
            "scan_status": f.scan_status,
        }
        file_node = _upsert_node(
            graph_session, node_cache, result,
            node_type="file", key=f.path, label=f.filename,
            properties=properties, track_incongruence=update,
        )
        _link_directory_chain(graph_session, node_cache, edge_cache, result, f.path, file_node)
        _link_media_type(graph_session, node_cache, edge_cache, result, file_node, f.extension or "")

        current_tags = tags_by_file.get(f.id, set()) if f.id is not None else set()
        for tag_name in current_tags:
            tag_node = _upsert_node(
                graph_session, node_cache, result,
                node_type="tag", key=tag_name, label=tag_name,
                properties={}, track_incongruence=False,
            )
            if file_node.id is not None and tag_node.id is not None:
                _upsert_edge(
                    graph_session, edge_cache, result,
                    source_id=file_node.id, target_id=tag_node.id, relation="HAS_TAG",
                )
        if update:
            _prune_stale_tag_edges(graph_session, result, node_cache, file_node, current_tags)

    # Pass 2: duplicate-group membership and DUPLICATE_OF edges (needs all file nodes present).
    for f in files:
        if not f.is_duplicate or not f.sha256:
            continue
        dup_file_node = node_cache.get(("file", f.path))
        if dup_file_node is None or dup_file_node.id is None:
            continue

        group_node = _upsert_node(
            graph_session, node_cache, result,
            node_type="duplicate_group", key=f.sha256, label=f"dup:{f.sha256[:12]}",
            properties={}, track_incongruence=False,
        )
        if group_node.id is not None:
            _upsert_edge(
                graph_session, edge_cache, result,
                source_id=dup_file_node.id, target_id=group_node.id, relation="MEMBER_OF",
            )

        canonical = by_id.get(f.canonical_file_id) if f.canonical_file_id else None
        if canonical is None:
            continue
        canonical_node = node_cache.get(("file", canonical.path))
        if canonical_node is not None and canonical_node.id is not None:
            _upsert_edge(
                graph_session, edge_cache, result,
                source_id=dup_file_node.id, target_id=canonical_node.id, relation="DUPLICATE_OF",
            )

    graph_session.flush()

    if update:
        _detect_removed_nodes(graph_session, result, node_type="file", current_keys=seen_paths)

    return result


def build_from_scan(scanner: BaseScanner, target: str, graph_session: Session, *, update: bool) -> GraphBuildResult:
    """Build or incrementally update the graph DB by walking the root directory fresh.

    Structural only (file/directory/media_type) — no hashes, tags, or duplicate
    groups, since those live only in the index DB (use source='sqlite' for those).
    """
    result = GraphBuildResult(mode="update" if update else "build", source="scan")

    if not update:
        _wipe_graph(graph_session)

    node_cache = _load_node_cache(graph_session)
    edge_cache = _load_edge_cache(graph_session)

    seen_paths: set[str] = set()

    for entry in scanner.scan(target):
        seen_paths.add(entry.path)
        properties = {
            "filename": entry.filename,
            "extension": entry.extension,
            "size_bytes": entry.size_bytes,
            "created_at": entry.created_at,
            "modified_at": entry.modified_at,
            "smb_uri": entry.smb_uri,
        }
        file_node = _upsert_node(
            graph_session, node_cache, result,
            node_type="file", key=entry.path, label=entry.filename,
            properties=properties, track_incongruence=update,
        )
        _link_directory_chain(graph_session, node_cache, edge_cache, result, entry.path, file_node)
        _link_media_type(graph_session, node_cache, edge_cache, result, file_node, entry.extension or "")

    graph_session.flush()

    if update:
        _detect_removed_nodes(graph_session, result, node_type="file", current_keys=seen_paths)

    return result


def write_incongruence_report(result: GraphBuildResult, graph_db_path: Path) -> Path:
    """Write the full incongruence list to a durable JSON report next to the graph DB,
    so an agentic harness reading files later can see what drifted — not just whoever
    watched the console at run time.
    """
    reports_dir = graph_db_path.parent / "graph_reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    payload = {
        "generated_at": _now(),
        "mode": result.mode,
        "source": result.source,
        "summary": {
            "nodes_created": result.nodes_created,
            "nodes_updated": result.nodes_updated,
            "nodes_removed": result.nodes_removed,
            "edges_created": result.edges_created,
            "edges_removed": result.edges_removed,
            "incongruences_count": result.incongruences_count,
        },
        "incongruences": [asdict(e) for e in result.incongruences],
    }
    content = json.dumps(payload, indent=2)

    report_path = reports_dir / f"graph_{result.source}_update_{timestamp}.json"
    report_path.write_text(content, encoding="utf-8")
    (reports_dir / f"graph_{result.source}_update_latest.json").write_text(content, encoding="utf-8")

    log.info("graph.incongruence_report_written", path=str(report_path))
    return report_path
