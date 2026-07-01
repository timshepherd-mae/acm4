# acm4/geom_helpers.py


from qgis.core import (
    QgsGeometry,
    QgsFeature,
    QgsPoint,
    QgsPointXY,
    QgsRasterLayer,
    QgsVectorLayer,
    QgsCoordinateTransform,
    QgsCoordinateTransformContext,
    QgsProject,
    QgsWkbTypes,
    QgsVectorFileWriter,
)

import os, tempfile
import math
from typing import Tuple, List


# ---------------------------
# Public API
# ---------------------------

def get_offset_mask(aoi_geom: QgsGeometry,
                    offset: float,
                    crs_authid: str,
                    persist_to_gpkg: bool = True,
                    heal: bool = True,
                    segments: int = 24):
    """
    Create an offset polygon (cutline) from AOI geometry.

    Returns:
        (offset_geom: QgsGeometry, path_mask_clip_or_None: str|None)

    Behavior:
        - If heal=True, attempt robust healing sequence for GDAL.
        - If anything fails in healing, fall back to a basic buffer(offset).
        - If persist_to_gpkg=True, write the single-feature cutline to a temp GPKG and
          return its file path (recommended for GDAL reliability).
    """
    # 1) Basic offset first; raise early if AOI is invalid
    if aoi_geom is None or aoi_geom.isEmpty():
        raise ValueError("AOI geometry is empty/invalid")

    try:
        # basic offset using buffer (positive expands; negative shrinks)
        offset_geom = aoi_geom.buffer(offset, segments)
        if offset_geom is None or offset_geom.isEmpty():
            raise ValueError("Offset operation produced empty geometry.")

        # optional healing
        if heal:
            offset_geom = _heal_for_gdal(offset_geom, segments=segments)

    except Exception:
        # Fall back to basic offset (no healing)
        offset_geom = aoi_geom.buffer(offset, segments)
        if offset_geom is None or offset_geom.isEmpty():
            # last resort: raise—caller can decide how to proceed
            raise

    # Persist if requested (GDAL likes real cutline files)
    path_mask_clip = None
    if persist_to_gpkg:
        path_mask_clip = _write_mask_to_gpkg(offset_geom, crs_authid)

    return offset_geom, path_mask_clip


def build_corridor_products(
    centerline2d: QgsGeometry,
    dtm_raster: QgsRasterLayer,
    width: float,
    separation: float,
    *,
    dtm_band: int = 1
) -> Tuple[QgsGeometry, QgsGeometry, QgsGeometry]:
    """
    Construct corridor boundary and derived products in pure PyQGIS (QGIS 3.44).

    Inputs
    ------
    centerline2d : QgsGeometry
        A single 2D LineString (or MultiLineString; it will be linearized/merged).
        Assumed to be in the *project CRS*.
    dtm_raster   : QgsRasterLayer
        Raster DEM/DTM layer used to sample Z values.
    width        : float
        Total corridor width (map units). Offsets are built at ± width/2.
    separation   : float
        Vertex spacing for densifying the offset lines (map units).
    dtm_band     : int
        DTM band index to sample (default 1).

    Returns
    -------
    (multipointZ, multiline2D, polygon2D) : Tuple[QgsGeometry, QgsGeometry, QgsGeometry]
        multipointZ : QgsGeometry (MultiPointZ) of boundary vertices with Z from DTM
        multiline2D : QgsGeometry (MultiLineString 2D) of exploded boundary segments
        polygon2D   : QgsGeometry (Polygon 2D) built from the closed boundary
    """

    if centerline2d is None or centerline2d.isEmpty():
        raise ValueError("centerline2d is empty.")
    if dtm_raster is None or not isinstance(dtm_raster, QgsRasterLayer) or not dtm_raster.isValid():
        raise ValueError("dtm_raster must be a valid QgsRasterLayer.")
    if width <= 0:
        raise ValueError("width must be > 0.")
    if separation <= 0:
        raise ValueError("separation must be > 0.")

    # --- 0) Normalize centerline: linearize & merge to a simple LineString (2D) ---
    cl = centerline2d
    cl = cl.flattenToLines() if hasattr(cl, "flattenToLines") else cl

    if cl.isMultipart():
        multiline = cl.asMultiPolyline()
        pts: List[QgsPointXY] = []
        for seg in multiline:
            for p in seg:
                pts.append(QgsPointXY(p))
        cl = QgsGeometry.fromPolylineXY(pts)
    else:
        if cl.type() != QgsWkbTypes.LineGeometry:
            raise TypeError("centerline2d must be a line geometry.")
        pts = [QgsPointXY(p) for p in cl.asPolyline()]
        cl = QgsGeometry.fromPolylineXY(pts)

    # --- 1) Build left/right offset lines at ± width/2 (QGIS 3.44 requires full signature) ---
    half_w = width / 2.0
    segments = 2                              # roundness detail for corners
    join_style = QgsGeometry.JoinStyleRound   # or JoinStyleMiter / JoinStyleBevel
    miter_limit = 2.0                         # relevant for miter joins

    left  = cl.offsetCurve(+half_w, segments, join_style, miter_limit)
    right = cl.offsetCurve(-half_w, segments, join_style, miter_limit)
    if left.isEmpty() or right.isEmpty():
        raise RuntimeError("Offset curve failed (check geometry validity and width).")

    # --- 2) Densify each offset line by 'separation' ---
    left_d  = left.densifyByDistance(separation)
    right_d = right.densifyByDistance(separation)

    left_pts  = _line_to_points_xy(left_d)
    right_pts = _line_to_points_xy(right_d)
    if len(left_pts) < 2 or len(right_pts) < 2:
        raise RuntimeError("Densification produced too few points; adjust separation or input geometry.")

    # --- 3) Reverse the second offset line, then join to form a closed boundary ring ---
    right_pts.reverse()
    boundary_ring: List[QgsPointXY] = left_pts + right_pts
    if not boundary_ring:
        raise RuntimeError("Boundary ring construction failed (no points).")
    if boundary_ring[0] != boundary_ring[-1]:
        boundary_ring.append(boundary_ring[0])

    # --- 4) Build MultiLineString of exploded segments (breaklines) ---
    segs_mls: List[List[QgsPointXY]] = []
    for i in range(len(boundary_ring) - 1):  # last equals first (closed)
        a = boundary_ring[i]
        b = boundary_ring[i + 1]
        segs_mls.append([a, b])
    breaklines_mls = QgsGeometry.fromMultiPolylineXY(segs_mls)

    # --- 5) Build polygon from the boundary ring (2D) ---
    polygon2d = QgsGeometry.fromPolygonXY([boundary_ring])

    # --- 6) Raster Z sampling at nearest centerline XY (transform project->raster CRS if needed) ---
    project_crs = QgsProject.instance().crs()
    raster_crs  = dtm_raster.crs()

    try:
        if project_crs != raster_crs:
            xform = QgsCoordinateTransform(project_crs, raster_crs, QgsProject.instance())
        else:
            xform = None
    except Exception:
        xform = None

    provider = dtm_raster.dataProvider()
    z_points: List[QgsPoint] = []

    for pt in boundary_ring[:-1]:  # exclude duplicated last vertex
        # Nearest point on centerline
        nearest_pt = cl.nearestPoint(QgsGeometry.fromPointXY(pt)).asPoint()
        sample_xy = QgsPointXY(nearest_pt.x(), nearest_pt.y())

        # Transform to raster CRS if needed
        sample_xy_for_raster = sample_xy
        if xform:
            try:
                sample_xy_for_raster = xform.transform(sample_xy)
            except Exception:
                pass

        # Primary sample at nearest centerline XY
        z_val = _sample_raster_value(provider, sample_xy_for_raster, dtm_band)

        # Fallback: sample at the boundary vertex XY
        if z_val is None:
            alt_xy = pt
            if xform:
                try:
                    alt_xy = xform.transform(pt)
                except Exception:
                    pass
            z_val = _sample_raster_value(provider, alt_xy, dtm_band)

        # Final fallback: zero
        if z_val is None:
            z_val = 0.0

        z_points.append(QgsPoint(pt.x(), pt.y(), z_val))

    # --- 7) Build MultiPointZ robustly for QGIS 3.44 ---
    multipointZ = _make_multipoint_z(z_points)
    if multipointZ.isEmpty():
        raise RuntimeError("Failed to construct MultiPointZ geometry from raster-sampled points.")
    # (Sanity checks)
    assert QgsWkbTypes.isMultiType(multipointZ.wkbType()), "Multipoint is not multi"
    assert QgsWkbTypes.hasZ(multipointZ.wkbType()), "Multipoint is not Z-enabled"

    return multipointZ, breaklines_mls, polygon2d




# ---------------------------
# Internal helpers
# ---------------------------

def _heal_for_gdal(geom: QgsGeometry, segments: int = 8) -> QgsGeometry:
    """
    Apply a robust sequence so GDAL's cutline never drops a corner:
      - makeValid
      - buffer(0, segments) to heal spikes/slivers
      - drop Z/M
      - force RHR (Right-Hand Rule) or orientate
      - normalize to MultiPolygon
      - rewrite via WKT to snap closing segment
    """
    g = geom.makeValid()
    g = g.buffer(0, segments)      # REQUIRED 2nd arg in QGIS 3.44
    g = g.make2D()
    try:
        g = g.forceRHR()           # reliable ring orientation
    except Exception:
        try:
            g = g.orientate()
        except Exception:
            pass
    g = _to_multipolygon(g)

    # Rewriting via WKT often snaps start/end epsilon issues
    g = QgsGeometry.fromWkt(g.asWkt())
    return g


def _to_multipolygon(geom: QgsGeometry) -> QgsGeometry:
    """Ensure geometry is MultiPolygon for consistent GDAL behavior."""
    # If it's polygon but not multi, rebuild as MULTIPOLYGON WKT
    if QgsWkbTypes.flatType(geom.wkbType()) == QgsWkbTypes.Polygon:
        return QgsGeometry.fromWkt(f"MULTI{geom.asWkt()[len('Polygon'):]}")
    return geom


def _write_mask_to_gpkg(geom: QgsGeometry, crs_authid: str) -> str:
    """
    Write a single-feature (Multi)Polygon to a temp GPKG and return its file path.
    """
    fd, gpkg_path = tempfile.mkstemp(prefix="acm4_mask_", suffix=".gpkg")
    os.close(fd)

    is_multi = QgsWkbTypes.isMultiType(geom.wkbType()) or \
               QgsWkbTypes.flatType(geom.wkbType()) == QgsWkbTypes.MultiPolygon
    gtype = "MultiPolygon" if is_multi else "Polygon"

    vl = QgsVectorLayer(f"{gtype}?crs={crs_authid}", "mask", "memory")
    pr = vl.dataProvider()
    f = QgsFeature(vl.fields())
    f.setGeometry(geom)
    pr.addFeatures([f])
    vl.updateExtents()

    opts = QgsVectorFileWriter.SaveVectorOptions()
    opts.driverName = "GPKG"
    opts.layerName = "mask"

    err, _, _, _ = QgsVectorFileWriter.writeAsVectorFormatV3(
        vl, gpkg_path, QgsCoordinateTransformContext(), opts
    )
    if err != QgsVectorFileWriter.NoError:
        raise ValueError(f"Failed to write mask GPKG: code {err}")

    return gpkg_path
    
