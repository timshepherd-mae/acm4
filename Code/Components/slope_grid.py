
# ============================================================
# acm4/slope_grid.py
# QGIS 4.0 — XY grid + slope filter (Point 2D, NO attributes)
# Pixel-aligned raster sampling (geoTransform-aware) to avoid zeroing.
# Recreates entire GPKG; layername == filename stem.
# Lock-safe on Windows; Processing-free; deterministic.
# Returns fully-qualified URI: "<path>.gpkg|layername=<stem>"
# ============================================================

import math
from pathlib import Path

from qgis.core import (
    QgsPointXY, QgsFeature, QgsGeometry, QgsVectorLayer, QgsRasterLayer,
    QgsProject, QgsCoordinateTransform, QgsCoordinateReferenceSystem,
    QgsFields, QgsWkbTypes, QgsVectorFileWriter
)

import processing

# use your out_helpers for unlocking
from .out_helpers import _try_remove_layer_for_path as _unlock_exact_path


# ------------------------------------------------------------
# Optional wrapper used by your ACM pipeline
# ------------------------------------------------------------

def do(raster_slope, raster_dtm, vector_extents, slope_threshold, density_steep, density_shallow, debug):
    """ACM entry point: builds two geometry-only point grids (steep & shallow).
    Returns (path_vector_gridpoints_steep, path_vector_gridpoints_shallow).
    Note: raster_dtm is unused here (Z draping happens in a later step by design).
    """
    from .out_helpers import _temp_vector, add_vector

    # deterministic output file paths (will be recreated)
    path_vector_gridpoints_steep = _temp_vector("point_grid_steep")
    path_vector_gridpoints_shallow = _temp_vector("point_grid_shallow")
    path_vector_gridpoints_steepZ = _temp_vector("point_grid_steepZ")
    path_vector_gridpoints_shallowZ = _temp_vector("point_grid_shallowZ")

    # STEEP (slope >= threshold)
    path_vector_gridpoints_steep = generate_filtered_grid_xy(
        slope_raster_path=raster_slope,
        extent_vector_path=vector_extents,
        existing_vector_path=path_vector_gridpoints_steep,
        xy_gap=density_steep,
        threshold=slope_threshold,
        select_less_than=False,
        debug=False,
    )

    # SHALLOW (slope < threshold) — use density_shallow (fix from earlier version)
    path_vector_gridpoints_shallow = generate_filtered_grid_xy(
        slope_raster_path=raster_slope,
        extent_vector_path=vector_extents,
        existing_vector_path=path_vector_gridpoints_shallow,
        xy_gap=density_shallow,
        threshold=slope_threshold,
        select_less_than=True,
        debug=False,
    )

    # PROMOTE STEEP POINTS TO Z
    result = processing.run("native:setzfromraster",
        {
            "INPUT": path_vector_gridpoints_steep,
            "RASTER": raster_dtm,
            "BAND": 1,
            "OUTPUT": path_vector_gridpoints_steepZ
        }
    )

    # PROMOTE SHALLOW POINTS TO Z
    result = processing.run("native:setzfromraster",
        {
            "INPUT": path_vector_gridpoints_shallow,
            "RASTER": raster_dtm,
            "BAND": 1,
            "OUTPUT": path_vector_gridpoints_shallowZ
        }
    )


    if debug:
        # Add to project tree for visual check (optional)
        add_vector(path_vector_gridpoints_steep, "steep")
        add_vector(path_vector_gridpoints_shallow, "shallow")
        add_vector(path_vector_gridpoints_steepZ, "steep pointZ")
        add_vector(path_vector_gridpoints_shallowZ, "shallow pointZ")

    return path_vector_gridpoints_steepZ, path_vector_gridpoints_shallowZ


# ---------------------- helpers ---------------------- #

def _split_gpkg_uri(uri: str):
    """Return (base_path, layername or None) from '<path>.gpkg[|layername=...]'."""
    parts = uri.split("|")
    base = parts[0]
    lname = None
    for p in parts[1:]:
        if p.lower().startswith("layername="):
            lname = p.split("=", 1)[1]
            break
    return base, lname

# 


def _derive_layername(path: str) -> str:
    """Default: 'C:/.../point_grid_steep.gpkg' -> 'point_grid_steep'."""
    return Path(path).stem or "layer"


def _unlock_gpkg_all(base_path: str):
    """Remove any map layers that reference this GPKG (with or without |layername=)."""
    # exact-path unlock via your helper
    try:
        _unlock_exact_path(Path(base_path))
    except Exception:
        pass

    # also remove gpkg|layername=... layers sharing this base path
    proj = QgsProject.instance()
    base_norm = base_path.replace("\\", "/")
    to_remove = [
        lid for lid, lyr in proj.mapLayers().items()
        if lyr.source().replace("\\", "/").startswith(base_norm)
    ]
    for lid in to_remove:
        proj.removeMapLayer(lid)


def _ensure_point_table(path_in: str, crs_authid: str) -> str:
    """
    Recreate a GPKG containing ONE Point(2D) geometry-only layer.
    Returns fully-qualified '...gpkg|layername=...'.
    """
    base, lname = _split_gpkg_uri(path_in)
    if not lname:
        lname = _derive_layername(base)

    base_path = Path(base)
    base_path.parent.mkdir(parents=True, exist_ok=True)

    _unlock_gpkg_all(str(base_path))

    # Always recreate the file (per user choice A)
    if base_path.exists():
        try:
            base_path.unlink()
        except PermissionError:
            _unlock_gpkg_all(str(base_path))
            base_path.unlink()

    fields = QgsFields()  # no attributes
    opts = QgsVectorFileWriter.SaveVectorOptions()
    opts.driverName = "GPKG"
    opts.layerName = lname
    opts.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteFile

    writer = QgsVectorFileWriter.create(
        str(base_path),
        fields,
        QgsWkbTypes.Point,  # 2D point
        QgsCoordinateReferenceSystem(crs_authid),
        QgsProject.instance().transformContext(),
        opts
    )
    if writer is None or writer.hasError() != QgsVectorFileWriter.NoError:
        err = None if writer is None else writer.errorMessage()
        raise ValueError(f"Failed to create GPKG '{base}': {err}")
    del writer  # flush+close

    return f"{base}|layername={lname}"


# --- QGIS 4.0 robust raster sampling helpers ---

def _get_geotransform(rl: QgsRasterLayer):
    """Return (originX, pixelW, rotX, originY, rotY, pixelH). pixelH often negative (north-up)."""
    prov = rl.dataProvider()
    gt = getattr(prov, 'geoTransform', None)
    gt = gt() if callable(gt) else None
    if gt is None or len(gt) != 6:
        # Fallback: assume north-up, compute from extent and size
        ext = rl.extent()
        w, h = rl.width(), rl.height()
        x0 = ext.xMinimum()
        y0 = ext.yMaximum()  # top edge
        pxW = ext.width() / max(1, w)
        pxH = -ext.height() / max(1, h)  # negative for north-up
        return (x0, pxW, 0.0, y0, 0.0, pxH)
    return gt


def _snap_to_center_in_raster_crs(pt_ras: QgsPointXY, rl: QgsRasterLayer) -> QgsPointXY:
    """Snap an XY (already in raster CRS) to the nearest pixel centre using geoTransform."""
    x0, pxW, rotX, y0, rotY, pxH = _get_geotransform(rl)
    # Compute pixel indices for a top-left geotransform
    col = round((pt_ras.x() - x0) / pxW - 0.5)
    row = round((pt_ras.y() - y0) / pxH - 0.5)  # pxH can be negative
    x_c = x0 + (col + 0.5) * pxW
    y_c = y0 + (row + 0.5) * pxH
    return QgsPointXY(x_c, y_c)


def _sample_slope_qgis4(slope_layer: QgsRasterLayer,
                        prov,
                        pt_extent_xy: QgsPointXY,
                        to_ras: QgsCoordinateTransform | None,
                        band: int,
                        debug: bool = False,
                        dbg_limit: int = 50):
    """
    Transform extent->raster CRS, snap to pixel centre, sample.
    Normalises provider return to (value, ok_flag) regardless of tuple order.
    """
    # Transform to raster CRS if needed
    pt_ras = pt_extent_xy if to_ras is None else to_ras.transform(QgsPointXY(pt_extent_xy.x(), pt_extent_xy.y()))
    # Snap to pixel center using raster geotransform
    pt_ras = _snap_to_center_in_raster_crs(pt_ras, slope_layer)

    r = prov.sample(pt_ras, band)
    if not isinstance(r, tuple) or len(r) != 2:
        return (None, False)

    a, b = r

    def _is_bool_like(x):
        return isinstance(x, bool) or x in (True, False)

    def _is_num_like(x):
        try:
            float(x)
            return True
        except Exception:
            return False

    if _is_num_like(a) and _is_bool_like(b):
        val, ok = float(a), bool(b)
    elif _is_num_like(b) and _is_bool_like(a):
        val, ok = float(b), bool(a)
    else:
        # Fallback: assume (value, ok)
        try:
            val, ok = float(a), bool(b)
        except Exception:
            val, ok = None, False

    if debug:
        c = getattr(_sample_slope_qgis4, "_counter", 0)
        if c < dbg_limit:
            print(f"DEBUG SAMPLE: extentXY=({pt_extent_xy.x()}, {pt_extent_xy.y()}) "
                  f"rasXY=({pt_ras.x()}, {pt_ras.y()}) value={val} ok={ok}")
            setattr(_sample_slope_qgis4, "_counter", c + 1)

    return (val, ok)


# ---------------------- main ---------------------- #

def generate_filtered_grid_xy(
    slope_raster_path: str,
    extent_vector_path: str,
    existing_vector_path: str,
    xy_gap: float,
    threshold: float,
    select_less_than: bool,
    debug: bool = True,
) -> str:
    """
    Build an XY grid (geometry-only Points) inside a polygon, filtered by slope.
      - select_less_than == False  -> keep slope >= threshold  (steep)
      - select_less_than == True   -> keep slope <  threshold  (shallow)

    Returns: fully-qualified output URI '...gpkg|layername=...'.
    """

    # 1) Inputs
    slope = QgsRasterLayer(slope_raster_path, "slope_ras")
    if not slope.isValid():
        raise ValueError(f"slope raster failed: {slope_raster_path}")

    extent = QgsVectorLayer(extent_vector_path, "extent_poly", "ogr")
    if not extent.isValid():
        raise ValueError(f"extent polygon failed: {extent_vector_path}")

    # 2) Prepare output table (Point 2D, no attributes), deterministic (recreate)
    out_uri = _ensure_point_table(existing_vector_path, extent.crs().authid())
    out_lyr = QgsVectorLayer(out_uri, "grid_points", "ogr")
    if not out_lyr.isValid():
        raise ValueError(f"Failed to load output layer: {out_uri}")
    out_dp = out_lyr.dataProvider()

    # 3) Providers & transforms
    slope_prov = slope.dataProvider()
    crs_extent = extent.crs()
    crs_slope  = slope.crs()

    to_slope = None
    if crs_extent != crs_slope:
        to_slope = QgsCoordinateTransform(crs_extent, crs_slope, QgsProject.instance())

    # 4) Extent geom & bbox (in extent CRS)
    geoms = [f.geometry() for f in extent.getFeatures() if f.hasGeometry()]
    if not geoms:
        raise ValueError("extent polygon has no geometry")
    extent_poly = QgsGeometry.unaryUnion(geoms)
    bbox = extent_poly.boundingBox()

    # 5) Grid loops (extent CRS)
    nx = int(math.floor(bbox.width()  / xy_gap)) + 1
    ny = int(math.floor(bbox.height() / xy_gap)) + 1
    x0, y0 = bbox.xMinimum(), bbox.yMinimum()

    new_feats = []
    band = 1

    for ix in range(nx):
        x = x0 + ix * xy_gap
        for iy in range(ny):
            y = y0 + iy * xy_gap

            pt_extent = QgsPointXY(x, y)
            geom = QgsGeometry.fromPointXY(pt_extent)

            if not extent_poly.contains(geom):
                continue

            # robust sampling
            sval, ok = _sample_slope_qgis4(
                slope_layer=slope,
                prov=slope_prov,
                pt_extent_xy=pt_extent,
                to_ras=to_slope,
                band=band,
                debug=debug,
            )
            if not ok or sval is None:
                continue

            if select_less_than:
                if sval >= threshold:
                    continue
            else:
                if sval < threshold:
                    continue

            nf = QgsFeature(out_lyr.fields())  # geometry-only
            nf.setGeometry(geom)
            new_feats.append(nf)

    if new_feats:
        out_dp.addFeatures(new_feats)
        out_lyr.updateExtents()

    print(f"WROTE {out_lyr.featureCount()} features → {out_uri}")
    return out_uri
