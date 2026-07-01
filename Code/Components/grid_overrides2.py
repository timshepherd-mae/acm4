# -*- coding: utf-8 -*-
"""
Rotated Grid 3D with Breaklines (standalone, acm4-style temp outputs; no Extents).

Per override polygon (in Project CRS):
  • Build a rotated, axis-aligned grid in a local frame; keep nodes inside the polygon
  • Rotate nodes to world (Project CRS) and assign Z by six methods:
      - From DTM                      -> per-vertex DTM sample
      - From DSM                      -> per-vertex DSM sample
      - Max DTM Value of Region       -> constant = DTM zonal max over polygon
      - Min DTM Value of Region       -> constant = DTM zonal min over polygon
      - Average DTM Value of Region   -> constant = DTM zonal mean over polygon
      - Custom Z value                -> constant = user_z
  • Optional perimeter points + breaklines when UseBreakline is truthy:
      - breakline_gap is NULL/0   : grid–boundary intersections (outer ring only)
      - breakline_gap > 0         : interval sampling every <gap> along outer ring
      - breakline_gap < 0         : BOTH (intersections + interval |gap|)
      - OUTER ring vertices are always added as perimeter points
      - BREAKLINES (Option L2): write ONLY OUTER RING segments, split at perimeter points (holes ignored)
  • Polygon output: original polygon geometry, carries 'type'

Outputs (all via acm4 temp GPKGs created with _temp_vector):
  • PointZ: parent_fid (int), type (str), Z (double), ZMethod (str)
  • LineString (outer ring segments only): parent_fid (int), type (str)
  • Polygon (original geometry): parent_fid (int), type (str)

Requires PyQGIS (tested with QGIS 3.44).
"""

from typing import List, Optional, Tuple, Union
import math
import os
import qgis.core as qgc

from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsCoordinateTransformContext,
    QgsFeature,
    QgsFields,
    QgsField,
    QgsGeometry,
    QgsPoint,
    QgsPointXY,
    QgsProject,
    QgsRaster,
    QgsRasterLayer,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsProcessingFeatureSourceDefinition,
    QgsVectorDataProvider,
    QgsWkbTypes,
    Qgis,
    QgsMessageLog,
)

from qgis.analysis import QgsZonalStatistics as QZ

# --- acm4 helpers (relative first; fallback absolute) ---
try:
    from .out_helpers import _temp_vector, add_vector  # acm4 package style
except Exception:
    from out_helpers import _temp_vector, add_vector   # flat import fallback


# =============================================================================
# Public API: ALWAYS uses acm4 _temp_vector() to create temp outputs
# =============================================================================

def do(
    overrides_path: Union[str, QgsVectorLayer, QgsProcessingFeatureSourceDefinition],
    dtm_path: Union[str, QgsRasterLayer],
    dsm_path: Union[str, QgsRasterLayer],
    debug,
    *,
    include_boundary_points: bool = False,
    add_to_canvas: bool = False,
    points_layer_name: str = "RotGrid_Points3D",
    breaklines_layer_name: str = "RotGrid_Breaklines",
    polygons_layer_name: str = "RotGrid_Polygons",
) -> Tuple[str, str, str]:
    """
    Build rotated 3D grid points (+ outer-ring-only breaklines) per polygon and write three outputs
    into acm4 temporary GeoPackages created with _temp_vector(...).

    Returns: (points_src, breaklines_src, polygons_src)
    """

    # ---- Input field names (fixed attributes of the overrides layer)
    F_GRID_X = "grid_x_spacing"
    F_GRID_Y = "grid_y_spacing"
    F_ORIENT = "grid_orientation"
    F_ZSRC   = "HeightData_Source"
    F_USERZ  = "user_z"
    F_TYPE   = "type"
    F_USEBL  = "UseBreakline"
    F_GAP    = "breakline_gap"

    # ---- Load inputs
    vlyr = _load_vector_layer(overrides_path, "overrides")
    if qgc.QgsWkbTypes.geometryType(vlyr.wkbType()) != qgc.QgsWkbTypes.PolygonGeometry:
        raise ValueError("Overrides layer must be polygonal.")

    dtm = _load_raster_layer(dtm_path, "DTM") if dtm_path else None
    dsm = _load_raster_layer(dsm_path, "DSM") if dsm_path else None

    # ---- Operate in PROJECT CRS (e.g., EPSG:27700) and transform features to it
    project_crs: QgsCoordinateReferenceSystem = QgsProject.instance().crs()
    src_crs_input: QgsCoordinateReferenceSystem = vlyr.sourceCrs()
    work_crs: QgsCoordinateReferenceSystem = project_crs
    ctx: QgsCoordinateTransformContext = QgsProject.instance().transformContext()

    # ---- Create three temp GPKGs (acm4 style)
    gpkg_points_0    = _temp_vector("acm4_rotgrid_points_0")
    gpkg_break_0     = _temp_vector("acm4_rotgrid_lines_0")
    gpkg_polys_0     = _temp_vector("acm4_rotgrid_polys_0")

    gpkg_points_1    = _temp_vector("acm4_rotgrid_points_1")
    gpkg_break_1     = _temp_vector("acm4_rotgrid_lines_1")
    gpkg_polys_1     = _temp_vector("acm4_rotgrid_polys_1")

    # ---- Create layers inside the GPKGs (IN PROJECT CRS)
    points_src_0    = _create_gpkg_layer(gpkg_points_0,    points_layer_name,   QgsWkbTypes.PointZ,    work_crs, _schema_points())
    breaklines_src_0 = _create_gpkg_layer(gpkg_break_0,    breaklines_layer_name, QgsWkbTypes.LineString, work_crs, _schema_breaklines())
    polygons_src_0   = _create_gpkg_layer(gpkg_polys_0,    polygons_layer_name, QgsWkbTypes.Polygon,    work_crs, _schema_polygons())

    points_src_1    = _create_gpkg_layer(gpkg_points_1,    points_layer_name,   QgsWkbTypes.PointZ,    work_crs, _schema_points())
    breaklines_src_1 = _create_gpkg_layer(gpkg_break_1,    breaklines_layer_name, QgsWkbTypes.LineString, work_crs, _schema_breaklines())
    polygons_src_1   = _create_gpkg_layer(gpkg_polys_1,    polygons_layer_name, QgsWkbTypes.Polygon,    work_crs, _schema_polygons())

    # ---- Open layers and start editing
    pts0 = QgsVectorLayer(points_src_0, "points0", "ogr")
    bl0  = QgsVectorLayer(breaklines_src_0, "breaks0", "ogr")
    poly0= QgsVectorLayer(polygons_src_0, "poly0", "ogr")

    pts1 = QgsVectorLayer(points_src_1, "points1", "ogr")
    bl1  = QgsVectorLayer(breaklines_src_1, "breaks1", "ogr")
    poly1= QgsVectorLayer(polygons_src_1, "poly1", "ogr")

    # Validate
    for L, kind in [
        (pts0, "PointZ"), (bl0, "LineString"), (poly0, "Polygon"),
        (pts1, "PointZ"), (bl1, "LineString"), (poly1, "Polygon")
    ]:
        if not L.isValid():
            raise RuntimeError(f"Output layer invalid: {L.name()}")
        _assert_layer_is(L, kind)

    _assert_fields(pts0, ("parent_fid", "type", "Z", "ZMethod", "priority"))
    _assert_fields(pts1, ("parent_fid", "type", "Z", "ZMethod", "priority"))
    _assert_fields(bl0,  ("parent_fid", "type", "priority"))
    _assert_fields(bl1,  ("parent_fid", "type", "priority"))
    _assert_fields(poly0,("parent_fid", "type", "priority"))
    _assert_fields(poly1,("parent_fid", "type", "priority"))

    # Start editing all six layers
    for L in (pts0, bl0, poly0, pts1, bl1, poly1):
        L.startEditing()

    # Capabilities info (for all 6 output layers)
    for L, lbl in (
        (pts0,  "points (priority 0)"),
        (bl0,   "breaklines (priority 0)"),
        (poly0, "polygons (priority 0)"),
        (pts1,  "points (priority 1)"),
        (bl1,   "breaklines (priority 1)"),
        (poly1, "polygons (priority 1)")
    ):
        caps = L.dataProvider().capabilities()
        can_add = bool(caps & QgsVectorDataProvider.AddFeatures)
        QgsMessageLog.logMessage(
            f"[grid_overrides] {lbl}: editable={L.isEditable()} "
            f"can_add={can_add} wkb={qgc.QgsWkbTypes.displayString(L.wkbType())}",
            "grid_overrides", Qgis.Info
        )

    names = vlyr.fields().names()

    # Diagnostics counters
    feats_total = 0
    feats_with_spacing = 0
    points_written_total = 0
    lines_written_total = 0
    polys_written_total = 0

    # ---- Process each override polygon
    for ft in vlyr.getFeatures():

        priority = 0
        if "priority" in vlyr.fields().names():
            try:
                priority = int(ft["priority"])
            except Exception:
                priority = 0

        # choose which set this feature writes into
        ptsL  = pts0 if priority == 0 else pts1
        blL   = bl0  if priority == 0 else bl1
        polyL = poly0 if priority == 0 else poly1


        # --- DEBUG BLOCK ---
        print("---- GRID OVERRIDE DEBUG ----")
        print("FID:", ft.id())
        print("priority raw:", ft["priority"])
        print("priority parsed:", priority)
        print("names:", names)
        print("F_GRID_X in names:", F_GRID_X in names)
        print("F_GRID_Y in names:", F_GRID_Y in names)
        print("dx raw:", ft[F_GRID_X])
        print("dy raw:", ft[F_GRID_Y])
        print("------------------------------")


        feats_total += 1
        g = ft.geometry()
        if not g or g.isEmpty():
            continue
        try:
            g = g.makeValid()
        except Exception:
            pass

        # Transform feature geometry to PROJECT CRS if needed
        if src_crs_input != work_crs:
            try:
                g = QgsGeometry(g)
                g.transform(QgsCoordinateTransform(src_crs_input, work_crs, QgsProject.instance()))
            except Exception:
                continue

        # --- Write polygon feature (original geometry, with 'type')
        poly_f = _make_polygon_feature(polyL, g, ft, F_TYPE)
        poly_f["priority"] = priority
        polys_written_total += _safe_add(polyL, [poly_f], "polygons")

        # --- Spacing & orientation
        dx = _num_or_none(ft[F_GRID_X]) if F_GRID_X in names else None
        dy = _num_or_none(ft[F_GRID_Y]) if F_GRID_Y in names else None
        if dx is None or dy is None or dx <= 0 or dy <= 0:
            # polygon written; skip grid if spacing invalid
            continue
        feats_with_spacing += 1

        deg = _num_or_none(ft[F_ORIENT]) if F_ORIENT in names else 0.0
        if deg is None:
            deg = 0.0

        # --- Height method & per-feature values
        zsrc_raw = ft[F_ZSRC] if F_ZSRC in names else None
        method   = _normalize_height_method(zsrc_raw)  # dtm/dsm/max/min/mean/usr
        usr_val  = _num_or_none(ft[F_USERZ]) if F_USERZ in names else None
        tval     = ft[F_TYPE] if F_TYPE in names else None

        # --- Region stats (DTM) for max/min/mean -- run in PROJECT CRS
        region_z: Optional[float] = None
        if method in ("max", "min", "mean"):
            stats = _region_stats(g, work_crs, dtm, 1) if dtm is not None else {"min": None, "mean": None, "max": None}
            region_z = stats["max"] if method == "max" else stats["min"] if method == "min" else stats["mean"]

        # --- DEBUG: print region statistics ---
        print("Feature", ft.id(), "method =", method, "region_z =", region_z)

        # --- Rotate polygon to local frame (+deg about centroid)
        C = g.centroid().asPoint()
        Cxy = QgsPointXY(C.x(), C.y())

        Plocal = QgsGeometry(g)
        Plocal.rotate(+deg, Cxy)

        # --- Local bbox & grid origin
        bb = Plocal.boundingBox()
        minx, miny, maxx, maxy = bb.xMinimum(), bb.yMinimum(), bb.xMaximum(), bb.yMaximum()

        # --- Generate candidate lattice
        nx = int(max(0, math.floor((maxx - minx) / dx))) + 1
        ny = int(max(0, math.floor((maxy - miny) / dy))) + 1

        # --- Containment
        kept_local: List[QgsPointXY] = []
        if nx > 0 and ny > 0:
            accepts = (Plocal.intersects if include_boundary_points else Plocal.contains)
            for ix in range(nx):
                x = minx + ix * dx
                for iy in range(ny):
                    y = miny + iy * dy
                    pL = QgsPointXY(x, y)
                    if accepts(QgsGeometry.fromPointXY(pL)):
                        kept_local.append(pL)

        # Fallbacks: covers, then intersects, if nothing accepted
        if not kept_local and nx > 0 and ny > 0:
            for ix in range(nx):
                x = minx + ix * dx
                for iy in range(ny):
                    y = miny + iy * dy
                    pL = QgsPointXY(x, y)
                    if Plocal.covers(QgsGeometry.fromPointXY(pL)):
                        kept_local.append(pL)
        if not kept_local and nx > 0 and ny > 0:
            for ix in range(nx):
                x = minx + ix * dx
                for iy in range(ny):
                    y = miny + iy * dy
                    pL = QgsPointXY(x, y)
                    if Plocal.intersects(QgsGeometry.fromPointXY(pL)):
                        kept_local.append(pL)

        # --- Interior points → PointZ features (built from ptsL.fields())
        to_add_pts: List[QgsFeature] = []
        for pL in kept_local:
            gp = QgsGeometry.fromPointXY(pL)
            gp.rotate(-deg, Cxy)  # back to world (PROJECT CRS)
            if not g.intersects(gp):  # safety
                continue
            P = gp.asPoint()
            pt_world_xy = QgsPointXY(P.x(), P.y())
            z = _resolve_z(pt_world_xy, method, dtm, dsm, usr_val, zsrc_raw, region_z, work_crs, ctx)

            of = QgsFeature(ptsL.fields())
            of.setGeometry(QgsGeometry.fromPoint(QgsPoint(P.x(), P.y(), float(z))))
            of["parent_fid"] = int(ft.id())
            of["type"] = str(tval) if tval is not None else None
            of["Z"] = float(z)
            of["ZMethod"] = str(zsrc_raw).upper() if zsrc_raw is not None else ""
            of["priority"] = priority
            to_add_pts.append(of)

        points_written_total += _safe_add(ptsL, to_add_pts, "points (interior)")

        # --- Perimeter points + breaklines (Option L2: OUTER ring only)
        use_bl = _truthy(ft[F_USEBL]) if F_USEBL in names else False
        if use_bl:
            gap_val = _num_or_none(ft[F_GAP]) if F_GAP in names else None

            # OUTER ring intersections in local frame → rotate back to world (PROJECT CRS)
            def compute_grid_intersections_world_outer() -> List[QgsPoint]:
                loc_pts = _gridline_intersections_with_boundary_outer(Plocal, dx, dy, minx, miny, maxx, maxy, eps=1e-9)
                out = []
                for pL2 in loc_pts:
                    gp2 = QgsGeometry.fromPointXY(pL2)
                    gp2.rotate(-deg, Cxy)
                    out.append(gp2.asPoint())
                return out

            # Interval sampling along OUTER ring only (world / PROJECT CRS)
            def compute_gap_points_world_outer(gap_spacing: float) -> List[QgsPointXY]:
                out2: List[QgsPointXY] = []
                for outer in _outer_rings(g):
                    out2.extend(_points_along_lines([outer], gap_spacing, include_end=False))
                return out2

            perim_pts_xy: List[QgsPointXY] = []
            if gap_val is None or gap_val == 0:
                pts_grid = compute_grid_intersections_world_outer()
                perim_pts_xy = [QgsPointXY(p.x(), p.y()) for p in pts_grid]
            elif gap_val > 0:
                pts_gap = compute_gap_points_world_outer(gap_val)
                perim_pts_xy = [QgsPointXY(p.x(), p.y()) for p in pts_gap]
            else:
                gap_abs = abs(gap_val)
                pts_grid = compute_grid_intersections_world_outer()
                pts_gap  = compute_gap_points_world_outer(gap_abs)
                perim_pts_xy = [QgsPointXY(p.x(), p.y()) for p in pts_grid] + pts_gap

            # Always add OUTER ring vertices (only)
            outer_vertices: List[QgsPointXY] = []
            for outer in _outer_rings(g):
                outer_vertices.extend(outer)

            merged_xy: List[QgsPointXY] = perim_pts_xy + outer_vertices
            unique_perim_xy = _dedupe_xy(merged_xy, tol=1e-7)

            # Perimeter points → PointZ
            to_add_perim: List[QgsFeature] = []
            for pt in unique_perim_xy:
                z = _resolve_z(pt, method, dtm, dsm, usr_val, zsrc_raw, region_z, work_crs, ctx)
                pf = QgsFeature(ptsL.fields())
                pf.setGeometry(QgsGeometry.fromPoint(QgsPoint(pt.x(), pt.y(), float(z))))
                pf["parent_fid"] = int(ft.id())
                pf["type"] = str(tval) if tval is not None else None
                pf["Z"] = float(z)
                pf["ZMethod"] = str(zsrc_raw).upper() if zsrc_raw is not None else ""
                pf["priority"] = priority
                to_add_perim.append(pf)

            points_written_total += _safe_add(ptsL, to_add_perim, "points (perimeter)")

            # OUTER ring breaklines only (ignore holes entirely)
            to_add_bl: List[QgsFeature] = []
            for outer in _outer_rings(g):
                if not outer or len(outer) < 2:
                    continue
                segs = _split_polyline_at_points(outer, unique_perim_xy, tol=1e-7)
                for seg in segs:
                    if not seg or len(seg) < 2:
                        continue
                    blf = QgsFeature(blL.fields())
                    blf.setGeometry(QgsGeometry.fromPolylineXY(seg))
                    blf["parent_fid"] = int(ft.id())
                    blf["type"] = str(tval) if tval is not None else None
                    blf["priority"] = priority
                    to_add_bl.append(blf)

            lines_written_total += _safe_add(blL, to_add_bl, "breaklines")


    # DEBUG: show which layers will be committed
    print("FINAL COMMIT TARGETS:", ptsL.name(), blL.name(), polyL.name())

    # ---- Commit, update, reload (AFTER the for-ft loop)
    for L, lbl in (
        (pts0,  "points0"),
        (bl0,   "breaklines0"),
        (poly0, "polygons0"),
        (pts1,  "points1"),
        (bl1,   "breaklines1"),
        (poly1, "polygons1")
    ):
        ok = True
        if L.isEditable():
            ok = L.commitChanges()
        L.updateExtents()
        try:
            L.reload()
        except:
            pass
        QgsMessageLog.logMessage(
            f"[grid_overrides] commit {lbl}: {ok}, features={L.featureCount()}",
            "grid_overrides"
        )

    # Optional: add to canvas using acm4 helper
    if debug or add_to_canvas:

        add_vector(points_src_0,    "5-GridOver - Points 3d (priority 0)")
        add_vector(breaklines_src_0,"5-GridOver - Breaklines (priority 0)")
        add_vector(polygons_src_0,  "5-GridOver - PolygonMask (priority 0)")
        add_vector(points_src_1,    "5-GridOver - Points 3d (priority 1)")
        add_vector(breaklines_src_1,"5-GridOver - Breaklines (priority 1)")
        add_vector(polygons_src_1,  "5-GridOver - PolygonMask (priority 1)")

        # try:
            # add_vector(points_src_0,    "GridOver - Points 3d (priority 0)")
            # add_vector(breaklines_src_0,"GridOver - Breaklines (priority 0)")
            # add_vector(polygons_src_0,  "GridOver - PolygonMask (priority 0)")
            # add_vector(points_src_1,    "GridOver - Points 3d (priority 1)")
            # add_vector(breaklines_src_1,"GridOver - Breaklines (priority 1)")
            # add_vector(polygons_src_1,  "GridOver - PolygonMask (priority 1)")
        # except Exception:
            # pass

    # Final summary
    QgsMessageLog.logMessage(
        f"[grid_overrides] feats={feats_total}, with_spacing={feats_with_spacing}, "
        f"points_written={points_written_total}, lines_written={lines_written_total}, polys_written={polys_written_total}",
        "grid_overrides", Qgis.Info
    )

    return (
        points_src_0, breaklines_src_0, polygons_src_0,
        points_src_1, breaklines_src_1, polygons_src_1
    )


# =============================================================================
# Feature-building, logging and layer/IO helpers
# =============================================================================

def _schema_points() -> QgsFields:
    f = QgsFields()
    f.append(QgsField("parent_fid", QVariant.Int))
    f.append(QgsField("type", QVariant.String, len=80))
    f.append(QgsField("Z", QVariant.Double, len=20, prec=3))
    f.append(QgsField("ZMethod", QVariant.String, len=64))
    f.append(QgsField("priority", QVariant.Int))
    return f

def _schema_breaklines() -> QgsFields:
    f = QgsFields()
    f.append(QgsField("parent_fid", QVariant.Int))
    f.append(QgsField("type", QVariant.String, len=80))
    f.append(QgsField("priority", QVariant.Int))
    return f

def _schema_polygons() -> QgsFields:
    f = QgsFields()
    f.append(QgsField("parent_fid", QVariant.Int))
    f.append(QgsField("type", QVariant.String, len=80))
    f.append(QgsField("priority", QVariant.Int))
    return f

def _assert_layer_is(layer: QgsVectorLayer, kind: str) -> None:
    gt = qgc.QgsWkbTypes.geometryType(layer.wkbType())
    if kind == "PointZ":
        assert gt == qgc.QgsWkbTypes.PointGeometry and qgc.QgsWkbTypes.hasZ(layer.wkbType()), \
            f"Layer is not PointZ: {qgc.QgsWkbTypes.displayString(layer.wkbType())}"
    elif kind == "LineString":
        assert gt == qgc.QgsWkbTypes.LineGeometry, \
            f"Layer is not LineString: {qgc.QgsWkbTypes.displayString(layer.wkbType())}"
    elif kind == "Polygon":
        assert gt == qgc.QgsWkbTypes.PolygonGeometry, \
            f"Layer is not Polygon: {qgc.QgsWkbTypes.displayString(layer.wkbType())}"

def _assert_fields(layer: QgsVectorLayer, required: Tuple[str, ...]) -> None:
    names = [f.name() for f in layer.fields()]
    for r in required:
        assert r in names, f"Missing field '{r}' in {layer.name()}"

def _safe_add(layer: QgsVectorLayer, feats: List[QgsFeature], label: str) -> int:
    if not feats:
        return 0
    ok = layer.addFeatures(feats)
    if not ok:
        QgsMessageLog.logMessage(
            f"[grid_overrides] addFeatures failed for {label} ({len(feats)})",
            "grid_overrides", Qgis.Critical
        )
        return 0
    return len(feats)

def _make_polygon_feature(poly_layer: QgsVectorLayer, g: QgsGeometry, ft: QgsFeature, type_field: str) -> QgsFeature:
    names = ft.fields().names()
    tval = ft[type_field] if type_field in names else None
    f = QgsFeature(poly_layer.fields())
    f.setGeometry(QgsGeometry(g))
    f["parent_fid"] = int(ft.id())
    f["type"] = str(tval) if tval is not None else None
    return f

def _create_gpkg_layer(
    gpkg_path: str,
    layer_name: str,
    wkb_type: qgc.QgsWkbTypes.GeometryType,
    crs: QgsCoordinateReferenceSystem,
    fields: QgsFields
) -> str:
    """Create (or overwrite) a GeoPackage layer and return its OGR source string."""
    os.makedirs(os.path.dirname(os.path.abspath(gpkg_path)), exist_ok=True)

    opts = QgsVectorFileWriter.SaveVectorOptions()
    opts.driverName = "GPKG"
    opts.layerName = layer_name
    opts.fileEncoding = "UTF-8"
    tctx = QgsCoordinateTransformContext()

    writer = QgsVectorFileWriter.create(
        fileName=gpkg_path,
        fields=fields,
        geometryType=wkb_type,
        srs=crs,
        transformContext=tctx,
        options=opts
    )
    if writer.hasError() != QgsVectorFileWriter.NoError:
        raise RuntimeError(f"Failed to create '{layer_name}' in {gpkg_path}: {writer.errorMessage()}")
    del writer
    return f"{gpkg_path}|layername={layer_name}"

def _load_vector_layer(src: Union[str, QgsVectorLayer, QgsProcessingFeatureSourceDefinition], name: str) -> QgsVectorLayer:
    # Already a layer object
    if isinstance(src, QgsVectorLayer):
        if not src.isValid():
            raise RuntimeError("Provided QgsVectorLayer is invalid.")
        return src
    # Processing wrapper
    if isinstance(src, QgsProcessingFeatureSourceDefinition):
        lyr = QgsVectorLayer(src.source, name, "ogr")
        if not lyr.isValid():
            raise RuntimeError(f"Failed to resolve feature source: {src.source}")
        return lyr
    # String OGR path
    if isinstance(src, str):
        lyr = QgsVectorLayer(src, name, "ogr")
        if not lyr.isValid():
            raise RuntimeError(f"Failed to load vector layer: {src}")
        return lyr
    raise TypeError(f"_load_vector_layer: unsupported src type {type(src).__name__}")

def _load_raster_layer(src: Union[str, QgsRasterLayer], name: str) -> QgsRasterLayer:
    if isinstance(src, QgsRasterLayer):
        if not src.isValid():
            raise RuntimeError("Provided QgsRasterLayer is invalid.")
        return src
    if isinstance(src, str):
        rl = QgsRasterLayer(src, name)
        if not rl.isValid():
            raise RuntimeError(f"Failed to load raster layer: {src}")
        return rl
    raise TypeError(f"_load_raster_layer: unsupported src type {type(src).__name__}")


# =============================================================================
# Geometry & sampling helpers
# =============================================================================

def _normalize_height_method(raw) -> str:
    """
    Normalize HeightData_Source enum values:

        DTM -> 'dtm'
        DSM -> 'dsm'
        MAX -> 'max'
        MIN -> 'min'
        AVE -> 'mean'
        USR -> 'usr'

    """
    if raw is None:
        return "dtm"

    s = str(raw).strip().upper()   # make it robust to case

    if s == "DTM":
        return "dtm"
    if s == "DSM":
        return "dsm"
    if s == "MAX":
        return "max"
    if s == "MIN":
        return "min"
    if s == "AVE":
        return "mean"          # AVERAGE → MEAN
    if s == "USR":
        return "usr"

    # fallback for textual values if they ever appear
    s_low = s.lower()
    if "custom" in s_low or "user" in s_low or "usr" in s_low or "attribute" in s_low:
        return "usr"
    if "max" in s_low:
        return "max"
    if "min" in s_low:
        return "min"
    if "ave" in s_low or "avg" in s_low or "mean" in s_low:
        return "mean"
    if "dsm" in s_low:
        return "dsm"
    if "dtm" in s_low:
        return "dtm"

    return "dtm"

def _truthy(val) -> bool:
    if val is None:
        return False
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in ("1", "true", "yes", "y", "t")

def _num_or_none(v) -> Optional[float]:
    try:
        if v is None:
            return None
        f = float(v)
        if math.isnan(f):
            return None
        return f
    except Exception:
        return None

def _frange(a: float, b: float, s: float, eps: float = 1e-9):
    n = 0
    while True:
        v = a + n * s
        if v > b + eps:
            break
        yield v
        n += 1

def _outer_rings(geom: QgsGeometry) -> List[List[QgsPointXY]]:
    """Return OUTER rings only (world) as lists of QgsPointXY."""
    rings = []
    if not geom or geom.isEmpty():
        return rings
    try:
        mpoly = geom.asMultiPolygon()
        if mpoly:
            for poly in mpoly:
                if poly and len(poly) > 0:
                    rings.append([QgsPointXY(p.x(), p.y()) for p in poly[0]])
            return rings
    except Exception:
        pass
    try:
        poly = geom.asPolygon()
        if poly and len(poly) > 0:
            rings.append([QgsPointXY(p.x(), p.y()) for p in poly[0]])
            return rings
    except Exception:
        pass
    # Fallback: first boundary ring if any
    bl = _boundary_lines(geom)
    if bl:
        rings.append(bl[0])
    return rings

def _boundary_lines(geom: QgsGeometry) -> List[List[QgsPointXY]]:
    """Return boundary parts (outer + holes) as lists of QgsPointXY."""
    lines = []
    if not geom or geom.isEmpty():
        return lines
    try:
        mpoly = geom.asMultiPolygon()
        if mpoly:
            for poly in mpoly:
                for ring in poly:
                    lines.append([QgsPointXY(p.x(), p.y()) for p in ring])
            return lines
    except Exception:
        pass
    try:
        poly = geom.asPolygon()
        if poly:
            for ring in poly:
                lines.append([QgsPointXY(p.x(), p.y()) for p in ring])
            return lines
    except Exception:
        pass
    try:
        g_line = QgsGeometry(geom)
        g_line.convertToType(qgc.QgsWkbTypes.LineString, False)
        ml = g_line.asMultiPolyline()
        if ml:
            for part in ml:
                lines.append([QgsPointXY(p.x(), p.y()) for p in part])
            return lines
        ln = g_line.asPolyline()
        if ln:
            lines.append([QgsPointXY(p.x(), p.y()) for p in ln])
    except Exception:
        pass
    return lines

def _points_along_lines(lines: List[List[QgsPointXY]], gap: float, include_end: bool = False,
                        eps: float = 1e-9) -> List[QgsPointXY]:
    pts: List[QgsPointXY] = []
    if not lines or gap is None or gap <= 0:
        return pts
    for line in lines:
        if not line:
            continue
        seglens, total = [], 0.0
        for i in range(1, len(line)):
            dx = line[i].x() - line[i-1].x()
            dy = line[i].y() - line[i-1].y()
            s = math.hypot(dx, dy)
            seglens.append(s)
            total += s
        d = 0.0
        while d <= total + eps:
            rem = d
            for i, s in enumerate(seglens):
                if rem <= s + eps:
                    x0, y0 = line[i].x(), line[i].y()
                    x1, y1 = line[i+1].x(), line[i+1].y()
                    t = 0.0 if s == 0 else max(0.0, min(1.0, rem / s))
                    px = x0 + t * (x1 - x0)
                    py = y0 + t * (y1 - y0)
                    pts.append(QgsPointXY(px, py))
                    break
                rem -= s
            d += gap
        if include_end and line:
            pts.append(line[-1])
    return pts

def _gridline_intersections_with_boundary_outer(Plocal: QgsGeometry,
                                                dx: float, dy: float,
                                                minx: float, miny: float, maxx: float, maxy: float,
                                                eps: float = 1e-9) -> List[QgsPointXY]:
    """
    Intersections (local frame) between axis-aligned grid lines and the OUTER ring(s).
      - verticals:   x = minx + n*dx
      - horizontals: y = miny + n*dy
    """
    xs, ys = [], []
    v = minx
    while v <= maxx + eps:
        xs.append(v); v += dx
    v = miny
    while v <= maxy + eps:
        ys.append(v); v += dy

    pts: List[QgsPointXY] = []
    rings = _outer_rings(Plocal)  # OUTER only
    for ring in rings:
        if not ring or len(ring) < 2:
            continue
        for i in range(1, len(ring)):
            x0, y0 = ring[i-1].x(), ring[i-1].y()
            x1, y1 = ring[i].x(), ring[i].y()
            # with verticals
            if abs(x1 - x0) > eps:
                x_min = x0 if x0 < x1 else x1
                x_max = x1 if x1 > x0 else x0
                for c in xs:
                    if c < x_min - eps or c > x_max + eps:
                        continue
                    t = (c - x0) / (x1 - x0)
                    if -eps <= t <= 1 + eps:
                        y = y0 + t * (y1 - y0)
                        pts.append(QgsPointXY(c, y))
            # with horizontals
            if abs(y1 - y0) > eps:
                y_min = y0 if y0 < y1 else y1
                y_max = y1 if y1 > y0 else y0
                for c in ys:
                    if c < y_min - eps or c > y_max + eps:
                        continue
                    t = (c - y0) / (y1 - y0)
                    if -eps <= t <= 1 + eps:
                        x = x0 + t * (x1 - x0)
                        pts.append(QgsPointXY(x, c))

    return _dedupe_xy(pts, tol=1e-7)

def _dedupe_xy(points: List[QgsPointXY], tol: float = 1e-7) -> List[QgsPointXY]:
    """De‑duplicate points by snapping to a tolerance grid."""
    seen, out = set(), []
    inv = 1.0 / tol
    for p in points:
        key = (int(round(p.x() * inv)), int(round(p.y() * inv)))
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out

def _split_polyline_at_points(line_pts: List[QgsPointXY], split_pts: List[QgsPointXY], tol: float = 1e-7):
    """
    Split a polyline (list of QgsPointXY) at given split points.
    Returns list of 2‑vertex segments [[A,B], [B,C], ...]. Zero‑length rejected.
    """
    segs_out = []
    if not line_pts or len(line_pts) < 2:
        return segs_out
    n = len(line_pts)
    for i in range(1, n):
        A = line_pts[i-1]; B = line_pts[i]
        ax, ay = A.x(), A.y()
        bx, by = B.x(), B.y()
        dx, dy = (bx - ax), (by - ay)
        seg_len2 = dx*dx + dy*dy
        if seg_len2 == 0:
            continue
        ts = [0.0, 1.0]
        for p in split_pts:
            px, py = p.x(), p.y()
            t = ((px - ax) * dx + (py - ay) * dy) / seg_len2
            if t < -1e-12 or t > 1 + 1e-12:
                continue
            qx, qy = (ax + t * dx, ay + t * dy)
            dd2 = (px - qx)**2 + (py - qy)**2
            if dd2 <= tol * tol:
                tt = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
                ts.append(tt)
        ts = sorted(set(round(t, 12) for t in ts))
        prevx, prevy = ax, ay
        for t in ts[1:]:
            qx, qy = ax + t * dx, ay + t * dy
            if (abs(qx - prevx) > tol) or (abs(qy - prevy) > tol):
                segs_out.append([QgsPointXY(prevx, prevy), QgsPointXY(qx, qy)])
            prevx, prevy = qx, qy
    return segs_out

def _region_stats(orig_geom: QgsGeometry,
                  vec_crs: QgsCoordinateReferenceSystem,
                  raster_layer: Optional[QgsRasterLayer],
                  band: int = 1) -> dict:
    """
    Compute min/mean/max of raster over the polygon.
    - Transforms the polygon into the raster CRS before running QgsZonalStatistics.
    - Returns {'min': float|None, 'mean': float|None, 'max': float|None}.
    """
    out = {'min': None, 'mean': None, 'max': None}
    if raster_layer is None or not orig_geom or orig_geom.isEmpty():
        return out

    raster_crs = raster_layer.crs()

    # Transform polygon → raster CRS
    poly_in_raster = QgsGeometry(orig_geom)
    if vec_crs != raster_crs:
        try:
            tr = QgsCoordinateTransform(vec_crs, raster_crs, QgsProject.instance())
            poly_in_raster.transform(tr)
        except Exception:
            # If we cannot transform, we cannot compute stats
            return out

    # One‑feature memory layer (in the raster CRS)
    tmp = QgsVectorLayer(f"Polygon?crs={raster_crs.authid()}", "tmp_zone", "memory")
    pr = tmp.dataProvider()
    pr.addAttributes([QgsField('id', QVariant.Int)])
    tmp.updateFields()

    f = QgsFeature(tmp.fields())
    f.setGeometry(poly_in_raster)
    f['id'] = 1
    pr.addFeature(f)
    tmp.updateExtents()

    # Min/Mean/Max
    flags = QZ.Mean | QZ.Min | QZ.Max
    QZ(tmp, raster_layer, 'zs_', band, flags).calculateStatistics(None)

    for r in tmp.getFeatures():
        out['min']  = _num_or_none(r['zs_min'])
        out['mean'] = _num_or_none(r['zs_mean'])
        out['max']  = _num_or_none(r['zs_max'])
        break

    return out
    
    
    
def _resolve_z(pt_world_xy: QgsPointXY,
               method: str,
               dtm: Optional[QgsRasterLayer],
               dsm: Optional[QgsRasterLayer],
               usr_val: Optional[float],
               zsrc_raw,
               region_z: Optional[float],
               src_crs: QgsCoordinateReferenceSystem,
               ctx: QgsCoordinateTransformContext) -> float:
    """
    Z resolver for both interior & perimeter points.
      method in {'dtm','dsm','max','min','mean','usr'}
    Fallback: numeric HeightData_Source -> float -> user_z -> 0.0
    """
    z = None
    if method == 'dtm':
        z = _sample_raster(pt_world_xy, dtm, src_crs, ctx, 1)
    elif method == 'dsm':
        z = _sample_raster(pt_world_xy, dsm, src_crs, ctx, 1)
    elif method in ('max', 'min', 'mean'):
        z = region_z
    elif method == 'usr':
        z = usr_val

    if z is None:
        try:
            z = float(zsrc_raw)
        except Exception:
            z = usr_val if usr_val is not None else 0.0

    return float(z)

def _sample_raster(pt_xy: QgsPointXY,
                   rlayer: Optional[QgsRasterLayer],
                   src_crs: QgsCoordinateReferenceSystem,
                   ctx: QgsCoordinateTransformContext,
                   band: int = 1) -> Optional[float]:
    """Identify/sample a raster value with on‑the‑fly CRS transform; returns float or None."""
    if rlayer is None:
        return None
    try:
        dst_crs = rlayer.crs()
        qpt = QgsCoordinateTransform(src_crs, dst_crs, ctx).transform(pt_xy) if dst_crs != src_crs else pt_xy
        ident = rlayer.dataProvider().identify(qpt, QgsRaster.IdentifyFormatValue)
        if not ident.isValid():
            return None
        vals = ident.results()
        val = vals.get(band, next(iter(vals.values()), None))
        return float(val) if val is not None else None
    except Exception:
        return None