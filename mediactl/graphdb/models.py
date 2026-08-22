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

SQLModel table definitions for the graph database.

Uses an isolated MetaData instance (graph_metadata) so these tables are never
created inside the main index DB (mediactl.db.models) or vice versa, even
though both a scan and a graph build may import each other's models in the
same process.

Node types: file, directory, tag, media_type, duplicate_group
Edge relations: CONTAINS, HAS_TAG, HAS_TYPE, DUPLICATE_OF, MEMBER_OF
"""
from __future__ import annotations

from sqlalchemy import MetaData, UniqueConstraint
from sqlmodel import Field, SQLModel

graph_metadata = MetaData()


class GraphBase(SQLModel):
    """Base for graph tables, isolated from mediactl.db.models' SQLModel.metadata."""

    metadata = graph_metadata


class GraphNode(GraphBase, table=True):
    """A node in the media graph (file, directory, tag, media_type, duplicate_group)."""

    __tablename__ = "graph_nodes"
    __table_args__ = (UniqueConstraint("node_type", "key", name="uq_graph_node_type_key"),)

    id: int | None = Field(default=None, primary_key=True)
    node_type: str = Field(index=True, nullable=False)
    key: str = Field(index=True, nullable=False)
    label: str = Field(nullable=False)
    properties: str | None = Field(default=None)  # JSON-encoded dict
    created_at: str = Field(nullable=False)
    updated_at: str = Field(nullable=False)


class GraphEdge(GraphBase, table=True):
    """A directed, typed relation between two graph nodes."""

    __tablename__ = "graph_edges"
    __table_args__ = (
        UniqueConstraint("source_id", "target_id", "relation", name="uq_graph_edge_triple"),
    )

    id: int | None = Field(default=None, primary_key=True)
    source_id: int = Field(foreign_key="graph_nodes.id", index=True, nullable=False)
    target_id: int = Field(foreign_key="graph_nodes.id", index=True, nullable=False)
    relation: str = Field(index=True, nullable=False)
    properties: str | None = Field(default=None)  # JSON-encoded dict
    created_at: str = Field(nullable=False)


class GraphRun(GraphBase, table=True):
    """Record of a graph build/update run, for history and `graph stats`."""

    __tablename__ = "graph_runs"

    id: int | None = Field(default=None, primary_key=True)
    started_at: str = Field(nullable=False)
    completed_at: str | None = Field(default=None)
    mode: str = Field(nullable=False)  # "build" | "update"
    source: str = Field(nullable=False)  # "sqlite" | "scan"
    nodes_created: int = Field(default=0)
    nodes_updated: int = Field(default=0)
    nodes_removed: int = Field(default=0)
    edges_created: int = Field(default=0)
    edges_removed: int = Field(default=0)
    incongruences_count: int = Field(default=0)
