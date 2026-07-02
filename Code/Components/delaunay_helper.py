# -*- coding: utf-8 -*-
# Build constrained Delaunay triangles (PolygonZ) from PointZ + optional (Multi)LineString breaklines.
# Signature required: build_triangulation(points_path, breaks_path, out_path)

import os
from pathlib import Path
import processing

from qgis.core import (
    QgsProject, QgsVectorLayer, QgsWkbTypes, QgsFeatureRequest, QgsGeometry,
    QgsPoint, QgsPointXY, QgsLineString, QgsSpatialIndex, QgsCoordinateTransform,
    QgsVectorFileWriter, QgsFields, QgsField, QgsFeature, QgsMessageLog, Qgis
)
from qgis.PyQt.QtCore import QVariant
from qgis.analysis import QgsMeshTriangulation



# ----------------------------
# Internal helpers
# ----------------------------

def _load_vector_first_layer(path_or_uri: str, name_hint="layer") -> QgsVectorLayer:
    """
    Load a vector layer from a simple file path (e.g. 'C:/data/a.gpkg' or '.shp').
    If it's a GPKG with multiple layers, auto-pick the first layer.
    If the caller already passed a URI with '|layername=', we use it as-is.
    """
    # If the caller passed a full OGR URI already, try that first.
    if "|layername=" in path_or_uri or "|layerid=" in path_or_uri:
        lyr = QgsVectorLayer(path_or_uri, name_hint, "ogr")
        if lyr and lyr.isValid():
            return lyr

    p = Path(path_or_uri)
    if not p.exists():
        raise RuntimeError(f"Path does not exist: {path_or_uri}")

    # Try direct load (works for SHP and single-layer GPKG)
    lyr = QgsVectorLayer(path_or_uri, name_hint, "ogr")
    if lyr and lyr.isValid():
        return lyr

    # If this is a GeoPackage with multiple layers, pick the first using GDAL/OGR
    if p.suffix.lower() == ".gpkg":
        try:
            from osgeo import ogr
            ds = ogr.Open(str(p))
            if ds is None or ds.GetLayerCount() == 0:
                raise RuntimeError(f"No layers found in {path_or_uri}")
            first_name = ds.GetLayer(0).GetName()
            uri = f"{path_or_uri}|layername={first_name}"
            lyr = QgsVectorLayer(uri, name_hint, "ogr")
            if lyr and lyr.isValid():
                return lyr
        except Exception as e:
            raise RuntimeError(
                f"Could not auto-select a layer in {path_or_uri}. "
                f"Either ensure it has a single layer or pass 'path|layername=…'.\nDetails: {e}"
            )
    # If all fail:
    raise RuntimeError(f"Failed to load vector layer from: {path_or_uri}")

def _require_pointz(layer: QgsVectorLayer, label="points"):
    if layer.geometryType() != QgsWkbTypes.PointGeometry or not QgsWkbTypes.hasZ(layer.wkbType()):
        raise RuntimeError(
            f"{label} layer must be PointZ/MultiPointZ; got {QgsWkbTypes.displayString(layer.wkbType())}"
        )

def _build_point_index(pointz_layer: QgsVectorLayer):
    """Spatial index + fid->(x,y,z) map (uses first vertex of each feature)."""
    idx = QgsSpatialIndex(pointz_layer.getFeatures())
    xyz = {}
    for f in pointz_layer.getFeatures(QgsFeatureRequest().setNoAttributes()):
        g = f.geometry()
        if not g or g.isEmpty():
            continue
        for v in g.vertices():
            if v.is3D():
                xyz[f.id()] = (v.x(), v.y(), v.z())
                break
    return idx, xyz

def _idw_z(x, y, idx, xyz, k=12, power=2.0):
    """IDW of Z from PointZ features (k nearest by bbox)."""
    if not xyz:
        return 0.0
    fids = idx.nearestNeighbor(QgsPointXY(x, y), k)
    num = den = 0.0
    for fid in fids:
        px, py, pz = xyz[fid]
        dx, dy = (px - x), (py - y)
        d2 = dx*dx + dy*dy
        if d2 == 0:
            return pz
        w = 1.0 / (d2 ** (power / 2.0))
        num += w * pz
        den += w
    return (num / den) if den else 0.0

def _breaklines_with_z(brk_layer: QgsVectorLayer, pts_layer: QgsVectorLayer, idx, xyz,
                       k=12, power=2.0) -> QgsVectorLayer:
    """
    Convert 2D (Multi)LineString into a LineStringZ memory layer — **one feature per part**.
    This is critical: CGAL constraints must be continuous (no discontinuities).
    """
    crs_authid = pts_layer.sourceCrs().authid()
    brkz = QgsVectorLayer(f"LineStringZ?crs={crs_authid}", "breaklines_z", "memory")
    dp = brkz.dataProvider()
    brkz.updateFields()

    # Reproject to points CRS if needed
    ct = QgsCoordinateTransform(brk_layer.sourceCrs(), pts_layer.sourceCrs(), QgsProject.instance())

    for f in brk_layer.getFeatures():
        g = f.geometry()
        if not g or g.isEmpty():
            continue
        gg = QgsGeometry(g)  # copy
        if brk_layer.sourceCrs() != pts_layer.sourceCrs():
            gg.transform(ct)

        # Emit each *part* as its own LineStringZ feature
        for part in gg.constParts():
            pts = []
            for v in part.vertices():
                z = _idw_z(v.x(), v.y(), idx, xyz, k=k, power=power)
                pts.append(QgsPoint(v.x(), v.y(), z))
            if len(pts) >= 2:
                geom = QgsGeometry(QgsLineString(pts))
                nf = QgsFeature()
                nf.setGeometry(geom)
                dp.addFeature(nf)

    brkz.updateExtents()
    return brkz

def _break_vertices_layer(linez_layer: QgsVectorLayer) -> QgsVectorLayer:
    """Extract vertices of LineStringZ into a PointZ memory layer."""
    crs_authid = linez_layer.sourceCrs().authid()
    ptl = QgsVectorLayer(f"PointZ?crs={crs_authid}", "break_vertices_z", "memory")
    dp = ptl.dataProvider()
    ptl.updateFields()
    for f in linez_layer.getFeatures():
        g = f.geometry()
        if not g or g.isEmpty():
            continue
        for v in g.vertices():
            nf = QgsFeature()
            nf.setGeometry(QgsGeometry.fromPoint(QgsPoint(v.x(), v.y(), v.z())))
            dp.addFeature(nf)
    ptl.updateExtents()
    return ptl

def _driver_for_path(path: str) -> str:
    lower = path.lower()
    if lower.endswith(".gpkg"):
        return "GPKG"
    if lower.endswith(".shp"):
        return "ESRI Shapefile"
    return "GPKG"

# ------------------------------------------------------------
# PUBLIC: exactly 3 parameters as requested
# ------------------------------------------------------------

def build_triangulation(points_path: str, breaks_path: str, out_path: str):
    """
    Build constrained Delaunay (PolygonZ) and write to 'out_path'.
    - points_path : path to existing PointZ/MultiPointZ dataset (GPKG/SHP).
    - breaks_path : path to existing LineString/MultiLineString (2D). Pass None/'' to skip.
    - out_path    : file path to write to (e.g., from _temp_vector('acm4_poly_delaunay')).

    Returns: out_path (string)
    """

    # ---------------- Load inputs from *paths only* ----------------
    pts_layer = _load_vector_first_layer(points_path, "points")
    _require_pointz(pts_layer, "points")

    brk_layer = None
    if breaks_path:
        brk_layer = _load_vector_first_layer(breaks_path, "breaklines")

        # ===================== #
        #      DIAGNOSTICS      #
        #                       #
        print("\n[DIAG] ===== TRIANGULATION INPUT =====")
        print(f"[DIAG] Points layer: {points_path}")
        print(f"[DIAG] Point count: {pts_layer.featureCount()}")

        if brk_layer:
            print(f"[DIAG] Breaklines layer: {breaks_path}")
            print(f"[DIAG] Breakline feature count: {brk_layer.featureCount()}")
        else:
            print("[DIAG] No breaklines provided")
        #                       #
        #      DIAGNOSTICS      #
        # ===================== #

        if brk_layer.geometryType() != QgsWkbTypes.LineGeometry:
            raise RuntimeError(f"breaklines must be a line layer; got {QgsWkbTypes.displayString(brk_layer.wkbType())}")

    # ---------------- Prep: point index (for IDW) ----------------

    idx, xyz = _build_point_index(pts_layer)

    # ===================== #
    #      DIAGNOSTICS      #
    #                       #
    print(f"[DIAG] Spatial index built")
    print(f"[DIAG] XYZ dict size: {len(xyz)}")
    #                       #
    #      DIAGNOSTICS      #
    # ===================== #

    # ---------------- Build constraints ----------------
    brkz_layer = None
    if brk_layer:
        brkz_layer = _breaklines_with_z(brk_layer, pts_layer, idx, xyz)  # one feature per part

        print("[DIAG] Cleaning breaklines for triangulation safety...")

        # STEP 1 — snap (fix precision / near-misses)
        snapped = processing.run("native:snapgeometries", {
            "INPUT": brkz_layer,
            "REFERENCE_LAYER": brkz_layer,
            "TOLERANCE": 0.001,  # adjust if needed
            "BEHAVIOR": 0,
            "OUTPUT": "memory:"
        })["OUTPUT"]

        # STEP 2 — node the network (CRITICAL)
        noded = processing.run("native:splitwithlines", {
            "INPUT": snapped,
            "LINES": snapped,
            "OUTPUT": "memory:"
        })["OUTPUT"]

        # STEP 3 — remove duplicates
        deduped = processing.run("native:deleteduplicategeometries", {
            "INPUT": noded,
            "OUTPUT": "memory:"
        })["OUTPUT"]

        # STEP 4 — explode to single segments (optional but safer)
        clean_breaks = processing.run("native:explodelines", {
            "INPUT": deduped,
            "OUTPUT": "memory:"
        })["OUTPUT"]

        print("[DIAG] Breakline cleaning complete")

        # ✅ USE CLEANED LAYER FROM HERE ON
        brkz_layer = clean_breaks

        # rebuild vertices from cleaned geometry

        brk_pts   = _break_vertices_layer(brkz_layer)
    else:
        brk_pts = None

    # ===================== #
    #      DIAGNOSTICS      #
    #                       #
    if brk_pts:
        print(f"[DIAG] Break vertices count: {brk_pts.featureCount()}")
    #                       #
    #      DIAGNOSTICS      #
    # ===================== #


    # ---------------- Triangulate ----------------

    tri = QgsMeshTriangulation()
    tri.setCrs(pts_layer.sourceCrs())
    # ===================== #
    #      DIAGNOSTICS      #
    #                       #
    print("\n[DIAG] ===== START TRIANGULATION =====")
    #                       #
    #      DIAGNOSTICS      #
    # ===================== #




    tri.addVertices(
        pts_layer.getFeatures(),
        -1,
        QgsCoordinateTransform(pts_layer.sourceCrs(), pts_layer.sourceCrs(), QgsProject.instance()),
        None,
        pts_layer.featureCount()
    )
    
    # ===================== #
    #      DIAGNOSTICS      #
    #                       #
    print("[DIAG] Vertices added to triangulation")
    #                       #
    #      DIAGNOSTICS      #
    # ===================== #


    if brkz_layer:

        # ===================== #
        #      DIAGNOSTICS      #
        #                       #
        print("\n[DIAG] ===== VALIDATING BREAKLINES =====")

        invalid_count = 0
        empty_count = 0
        bad_z_count = 0

        for f in brkz_layer.getFeatures():
            geom = f.geometry()

            if geom is None or geom.isEmpty():
                empty_count += 1
                continue

            if not geom.isGeosValid():
                invalid_count += 1

            # check Z values
            for v in geom.vertices():
                z = v.z()
                if z is None or z != z:  # NaN check
                    bad_z_count += 1
                    break

        print(f"[DIAG] Invalid geometries: {invalid_count}")
        print(f"[DIAG] Empty geometries: {empty_count}")
        print(f"[DIAG] Bad Z values: {bad_z_count}")

        print("[DIAG] Adding break vertices...")
        #                       #
        #      DIAGNOSTICS      #
        # ===================== #


        tri.addVertices(
            brk_pts.getFeatures(),
            -1,
            QgsCoordinateTransform(brk_pts.sourceCrs(), pts_layer.sourceCrs(), QgsProject.instance()),
            None,
            brk_pts.featureCount()
        )

        # ===================== #
        #      DIAGNOSTICS      #
        #                       #
        print("\n[DIAG] ===== CHECKING BREAKLINE INTERSECTIONS =====")

        from qgis.core import QgsSpatialIndex

        # features = list(brkz_layer.getFeatures())
        # index = QgsSpatialIndex(features)
        index = QgsSpatialIndex(brkz_layer.getFeatures())
        features = list(brkz_layer.getFeatures())

        intersection_count = 0

        for f in features:
            geom = f.geometry()
            if geom is None:
                continue

            # get nearby candidates
            candidate_ids = index.intersects(geom.boundingBox())

            for cid in candidate_ids:
                if cid == f.id():
                    continue

                other = brkz_layer.getFeature(cid)
                other_geom = other.geometry()

                if other_geom and geom.crosses(other_geom):
                    intersection_count += 1
                    if intersection_count < 5:
                        print(f"[DIAG] Intersection found between {f.id()} and {cid}")

        print(f"[DIAG] Total crossing intersections: {intersection_count}")
        print("[DIAG] Adding breaklines...")
        #                       #
        #      DIAGNOSTICS      #
        # ===================== #

        # ===================== #
        #      DIAGNOSTICS      #
        #                       #
        print("\n[DIAG] ===== CHECKING BREAKLINE VERTEX QUALITY =====")

        bad_segments = 0
        duplicate_vertices = 0

        for f in brkz_layer.getFeatures():
            geom = f.geometry()
            if not geom:
                continue

            prev = None
            for v in geom.vertices():
                pt = (round(v.x(), 8), round(v.y(), 8))

                if prev:
                    # duplicate vertex
                    if pt == prev:
                        duplicate_vertices += 1

                    # zero-length segment
                    dx = abs(pt[0] - prev[0])
                    dy = abs(pt[1] - prev[1])
                    if dx < 1e-9 and dy < 1e-9:
                        bad_segments += 1

                prev = pt

        print(f"[DIAG] Duplicate vertices: {duplicate_vertices}")
        print(f"[DIAG] Zero-length segments: {bad_segments}")
        #                       #
        #      DIAGNOSTICS      #
        # ===================== #

        # ===================== #
        #      DIAGNOSTICS      #
        #                       #
        

        multi_count = 0

        for f in brkz_layer.getFeatures():
            if QgsWkbTypes.isMultiType(f.geometry().wkbType()):
                multi_count += 1

        print(f"[DIAG] MultiLineString features: {multi_count}")
        #                       #
        #      DIAGNOSTICS      #
        # ===================== #



        # tri.addBreakLines(
        #     brkz_layer.getFeatures(),
        #     -1,
        #     QgsCoordinateTransform(brkz_layer.sourceCrs(), pts_layer.sourceCrs(), QgsProject.instance()),
        #     None,
        #     brkz_layer.featureCount()
        # )




        # ===================== #
        #      DIAGNOSTICS      #
        #                       #
        print("[DIAG] Breaklines added successfully")
        #                       #
        #      DIAGNOSTICS      #
        # ===================== #


    # ===================== #
    #      DIAGNOSTICS      #
    #                       #
    print("[DIAG] Running triangulatedMesh()...")
    #                       #
    #      DIAGNOSTICS      #
    # ===================== #


    mesh = tri.triangulatedMesh()

    # ===================== #
    #      DIAGNOSTICS      #
    #                       #
    print("[DIAG] Triangulation complete")
    #                       #
    #      DIAGNOSTICS      #
    # ===================== #

    # ===================== #
    #      DIAGNOSTICS      #
    #                       #
    face_count = mesh.faceCount()
    print(f"[DIAG] Face count: {face_count}")
    print(f"[DIAG] Estimated memory pressure: ~{face_count * 0.0005:.2f} MB (rough lower bound)")
    #                       #
    #      DIAGNOSTICS      #
    # ===================== #


    if not mesh or mesh.faceCount() == 0:
        #raise RuntimeError("Triangulation produced no faces — check inputs/constraints.")
        dummy = 0

    # ---------------- Emit PolygonZ and write to out_path ----------------
    crs = pts_layer.sourceCrs()
    mem = QgsVectorLayer(f"PolygonZ?crs={crs.authid()}", "triangles", "memory")
    dp  = mem.dataProvider()

    fields = QgsFields()
    fields.append(QgsField("face_id", QVariant.Int))
    dp.addAttributes(fields)
    mem.updateFields()

    total = mesh.faceCount()

    # ===================== #
    #      DIAGNOSTICS      #
    #                       #
    print("\n[DIAG] ===== BUILDING TRIANGLE FEATURES =====")
    print(f"[DIAG] Total faces to process: {total}")
    #                       #
    #      DIAGNOSTICS      #
    # ===================== #



    for i in range(total):

        # ===================== #
        #      DIAGNOSTICS      #
        #                       #
        if i % 10000 == 0:
            print(f"[DIAG] Processing face {i}/{total}")
        #                       #
        #      DIAGNOSTICS      #
        # ===================== #


        vids = mesh.face(i)
        ring = []
        for vid in vids:
            p = mesh.vertex(vid)
            ring.append(QgsPoint(p.x(), p.y(), p.z() if p.is3D() else 0.0))
        if ring and ring[0] != ring[-1]:
            ring.append(ring[0])

        wkt = "POLYGON Z((" + ", ".join(f"{pt.x()} {pt.y()} {pt.z()}" for pt in ring) + "))"
        f = QgsFeature(fields)
        f.setAttribute("face_id", i)
        f.setGeometry(QgsGeometry.fromWkt(wkt))
        dp.addFeature(f)

    # ===================== #
    #      DIAGNOSTICS      #
    #                       #
    print("[DIAG] Finished building memory layer")
    #                       #
    #      DIAGNOSTICS      #
    # ===================== #


    mem.updateExtents()

    # Choose driver by extension; default to GPKG

    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = _driver_for_path(out_path)

    if options.driverName == "GPKG":
        # use the base filename as the layer name (triangles)
        options.layerName = Path(out_path).stem

        if os.path.exists(out_path):
            # the container exists → update mode is valid: replace/overwrite the layer only
            options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
        else:
            # the container does NOT exist → create the file and the layer
            options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteFile
    else:
        # SHP/others: overwrite the whole file
        options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteFile


    # ===================== #
    #      DIAGNOSTICS      #
    #                       #
    print("[DIAG] Writing output to disk...")
    #                       #
    #      DIAGNOSTICS      #
    # ===================== #


    res, err, new_path, new_layer = QgsVectorFileWriter.writeAsVectorFormatV3(
        mem, out_path, QgsProject.instance().transformContext(), options
    )


    # ===================== #
    #      DIAGNOSTICS      #
    #                       #
    print("[DIAG] Write complete")
    #                       #
    #      DIAGNOSTICS      #
    # ===================== #


    if res != QgsVectorFileWriter.NoError:
        raise RuntimeError(f"Failed to write output: {err}")

    # ===================== #
    #      DIAGNOSTICS      #
    #                       #
    print("[DIAG] Cleaning up large objects")
    del mesh
    del tri
    del idx
    del xyz
    #                       #
    #      DIAGNOSTICS      #
    # ===================== #

 
    return out_path