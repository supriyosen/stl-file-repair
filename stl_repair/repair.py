from __future__ import annotations

from dataclasses import dataclass
import inspect
from pathlib import Path
from typing import Any

import numpy as np
import trimesh


@dataclass(frozen=True)
class RepairOptions:
    use_meshfix: bool = True
    join_components: bool = True
    remove_small_components: bool = False


def _load_mesh(path: str | Path) -> trimesh.Trimesh:
    loaded = trimesh.load(Path(path), force="mesh", process=False)
    if isinstance(loaded, trimesh.Scene):
        geometries = [geometry for geometry in loaded.geometry.values() if len(geometry.faces)]
        if not geometries:
            raise ValueError("No mesh geometry was found in the file.")
        loaded = trimesh.util.concatenate(geometries)
    if not isinstance(loaded, trimesh.Trimesh):
        raise ValueError(f"Unsupported mesh type: {type(loaded)!r}")
    if not len(loaded.vertices) or not len(loaded.faces):
        raise ValueError("The mesh has no vertices or faces.")
    return loaded


def _safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except Exception:
        return None
    if not np.isfinite(number):
        return None
    return number


def _component_count(mesh: trimesh.Trimesh) -> int | None:
    if len(mesh.faces) == 0:
        return 0
    parent = list(range(len(mesh.faces)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    face_ids = np.repeat(np.arange(len(mesh.faces)), 3)
    buckets: dict[int, list[int]] = {}
    for unique_edge_id, face_id in zip(mesh.edges_unique_inverse, face_ids, strict=False):
        buckets.setdefault(int(unique_edge_id), []).append(int(face_id))

    for faces in buckets.values():
        first = faces[0]
        for face_id in faces[1:]:
            union(first, face_id)

    return len({find(index) for index in range(len(mesh.faces))})


def _edge_counts(mesh: trimesh.Trimesh) -> tuple[int, int, int]:
    if len(mesh.faces) == 0:
        return 0, 0, 0
    edge_use = np.bincount(mesh.edges_unique_inverse)
    boundary_edges = int(np.count_nonzero(edge_use == 1))
    overused_edges = int(np.count_nonzero(edge_use > 2))
    non_manifold_edges = int(np.count_nonzero(edge_use != 2))
    return boundary_edges, overused_edges, non_manifold_edges


def _duplicate_face_count(mesh: trimesh.Trimesh) -> int:
    if len(mesh.faces) == 0:
        return 0
    sorted_faces = np.sort(np.asarray(mesh.faces), axis=1)
    unique_faces = np.unique(sorted_faces, axis=0)
    return int(len(sorted_faces) - len(unique_faces))


def _degenerate_face_count(mesh: trimesh.Trimesh) -> int:
    if len(mesh.faces) == 0:
        return 0
    areas = np.asarray(mesh.area_faces)
    return int(np.count_nonzero(~np.isfinite(areas) | (areas <= 1e-12)))


def _normalized_for_analysis(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    normalized = mesh.copy()
    try:
        normalized.remove_infinite_values()
    except Exception:
        pass
    normalized.merge_vertices()
    normalized.remove_unreferenced_vertices()
    return normalized


def analyze_mesh(mesh: trimesh.Trimesh) -> dict[str, Any]:
    mesh = _normalized_for_analysis(mesh)
    boundary_edges, overused_edges, non_manifold_edges = _edge_counts(mesh)
    extents = [_safe_float(value) for value in np.asarray(mesh.extents).tolist()]
    volume = _safe_float(abs(mesh.volume)) if mesh.is_watertight else None

    return {
        "vertices": int(len(mesh.vertices)),
        "triangles": int(len(mesh.faces)),
        "size_mm": extents,
        "volume_mm3": volume,
        "watertight": bool(mesh.is_watertight),
        "winding_consistent": bool(mesh.is_winding_consistent),
        "non_manifold_edges": non_manifold_edges,
        "boundary_edges": boundary_edges,
        "overused_edges": overused_edges,
        "duplicate_faces": _duplicate_face_count(mesh),
        "degenerate_faces": _degenerate_face_count(mesh),
        "components": _component_count(mesh),
        "euler_number": int(mesh.euler_number),
    }


def analyze_file(path: str | Path) -> dict[str, Any]:
    return analyze_mesh(_load_mesh(path))


def _mask_faces(mesh: trimesh.Trimesh, mask: np.ndarray, label: str, steps: list[str]) -> None:
    before = len(mesh.faces)
    if len(mask) != before:
        return
    removed = int(before - np.count_nonzero(mask))
    if removed:
        mesh.update_faces(mask)
        steps.append(f"Removed {removed} {label}.")


def _basic_cleanup(mesh: trimesh.Trimesh, steps: list[str]) -> trimesh.Trimesh:
    mesh = mesh.copy()

    try:
        mesh.remove_infinite_values()
    except Exception:
        pass

    if hasattr(mesh, "nondegenerate_faces"):
        _mask_faces(mesh, mesh.nondegenerate_faces(), "degenerate triangles", steps)
    elif hasattr(mesh, "remove_degenerate_faces"):
        before = len(mesh.faces)
        mesh.remove_degenerate_faces()
        removed = before - len(mesh.faces)
        if removed:
            steps.append(f"Removed {removed} degenerate triangles.")

    if hasattr(mesh, "unique_faces"):
        _mask_faces(mesh, mesh.unique_faces(), "duplicate triangles", steps)
    elif hasattr(mesh, "remove_duplicate_faces"):
        before = len(mesh.faces)
        mesh.remove_duplicate_faces()
        removed = before - len(mesh.faces)
        if removed:
            steps.append(f"Removed {removed} duplicate triangles.")

    before_vertices = len(mesh.vertices)
    mesh.merge_vertices()
    mesh.remove_unreferenced_vertices()
    merged = before_vertices - len(mesh.vertices)
    if merged:
        steps.append(f"Merged/removed {merged} duplicate or unused vertices.")

    try:
        trimesh.repair.fix_normals(mesh, multibody=True)
        steps.append("Reoriented face normals.")
    except Exception:
        try:
            trimesh.repair.fix_normals(mesh)
            steps.append("Reoriented face normals.")
        except Exception:
            pass

    try:
        if trimesh.repair.fill_holes(mesh):
            steps.append("Filled simple holes.")
    except Exception:
        pass

    try:
        trimesh.repair.fix_inversion(mesh, multibody=True)
    except Exception:
        pass

    return mesh


def _meshfix_available() -> bool:
    try:
        import pymeshfix  # noqa: F401
    except Exception:
        return False
    return True


def _run_meshfix(mesh: trimesh.Trimesh, options: RepairOptions, steps: list[str]) -> trimesh.Trimesh:
    import pymeshfix

    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    fixer = pymeshfix.MeshFix(vertices, faces)
    repair_kwargs = {
        "joincomp": options.join_components,
        "remove_smallest_components": options.remove_small_components,
    }
    accepted = inspect.signature(fixer.repair).parameters
    if "verbose" in accepted:
        repair_kwargs["verbose"] = False
    fixer.repair(**repair_kwargs)

    repaired = trimesh.Trimesh(
        vertices=np.asarray(getattr(fixer, "v", fixer.points), dtype=np.float64),
        faces=np.asarray(getattr(fixer, "f", fixer.faces), dtype=np.int64),
        process=False,
    )
    if not len(repaired.faces):
        raise ValueError("MeshFix returned an empty mesh.")

    steps.append("Ran MeshFix manifold reconstruction.")
    return repaired


def _needs_meshfix(report: dict[str, Any]) -> bool:
    return (
        report["non_manifold_edges"] > 0
        or report["boundary_edges"] > 0
        or report["overused_edges"] > 0
        or not report["watertight"]
    )


def repair_file(
    input_path: str | Path,
    output_path: str | Path | None = None,
    options: RepairOptions | None = None,
) -> dict[str, Any]:
    options = options or RepairOptions()
    input_path = Path(input_path)
    output_path = Path(output_path) if output_path else input_path.with_name(f"{input_path.stem}_repaired.stl")

    original = _load_mesh(input_path)
    before = analyze_mesh(original)
    steps: list[str] = []

    repaired = _basic_cleanup(original, steps)
    after_basic = analyze_mesh(repaired)

    meshfix_error = None
    meshfix_available = _meshfix_available()
    if options.use_meshfix and meshfix_available and _needs_meshfix(after_basic):
        try:
            repaired = _run_meshfix(repaired, options, steps)
            repaired = _basic_cleanup(repaired, steps)
        except Exception as exc:
            meshfix_error = str(exc)
            steps.append(f"MeshFix failed: {meshfix_error}")
    elif options.use_meshfix and not meshfix_available:
        steps.append("MeshFix is not installed; only basic cleanup was run.")

    after = analyze_mesh(repaired)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    repaired.export(output_path, file_type="stl")

    success = after["watertight"] and after["non_manifold_edges"] == 0 and after["triangles"] > 0
    return {
        "input": str(input_path),
        "output": str(output_path),
        "success": success,
        "meshfix_available": meshfix_available,
        "meshfix_error": meshfix_error,
        "before": before,
        "after": after,
        "steps": steps,
    }
