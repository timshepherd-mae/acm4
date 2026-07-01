# acm4/corridors.py


from qgis.core import (
    QgsVectorFileWriter, 
    QgsFields, 
    QgsField, 
    QgsWkbTypes,
    QgsProject, 
    QgsCoordinateTransformContext,
    QgsProcessingUtils, 
    QgsMessageLog, 
    Qgis,    
    QgsProject,
    QgsVectorLayer,
    QgsRasterLayer,
    QgsPoint
)
from qgis.PyQt.QtCore import QVariant

import processing
import os
from pathlib import Path



def _init_gpkg_layer(gpkg_path: str, layer_name: str, wkb_type: QgsWkbTypes.GeometryType, fields: QgsFields) -> str:
    """
    Creates (or overwrites) a single vector layer inside a GeoPackage.
    Returns the OGR connection string 'gpkg_path|layername=<layer_name>'.
    """
    opts = QgsVectorFileWriter.SaveVectorOptions()
    opts.driverName = "GPKG"
    opts.layerName = layer_name
    opts.fileEncoding = "UTF-8"
    # Important: pass a transform context
    tctx = QgsCoordinateTransformContext()
    srs = QgsProject.instance().crs()

    # Create (or append) the layer
    writer = QgsVectorFileWriter.create(
        fileName=gpkg_path,
        fields=fields,
        geometryType=wkb_type,
        srs=srs,
        transformContext=tctx,
        options=opts
    )
    if writer.hasError() != QgsVectorFileWriter.NoError:
        raise RuntimeError(f"Failed to create layer '{layer_name}' in {gpkg_path}: {writer.errorMessage()}")
    del writer  # flush and close

    return f"{gpkg_path}|layername={layer_name}"

def init_corridor_output_layers(
    points_gpkg_path: str,
    lines_gpkg_path: str,
    polys_gpkg_path: str,
    points_layer_name: str = "points3d",
    lines_layer_name: str = "breaklines",
    polys_layer_name: str = "corridors"
) -> tuple[str, str, str]:
    """
    Creates three layers (PointZ, LineString, Polygon with 'type') inside the three gpkg files.
    Returns the 3 OGR source strings to pass to the wrapper.
    """
    # PointZ (with optional pid field)
    f_pts = QgsFields()
    f_pts.append(QgsField("pid", QVariant.Int))
    points_src = _init_gpkg_layer(points_gpkg_path, points_layer_name, QgsWkbTypes.PointZ, f_pts)

    # LineString (no attributes required)
    f_ln = QgsFields()
    lines_src  = _init_gpkg_layer(lines_gpkg_path,  lines_layer_name,  QgsWkbTypes.LineString, f_ln)

    # Polygon (must have 'type' attribute)
    f_poly = QgsFields()
    f_poly.append(QgsField("type", QVariant.String))
    polys_src = _init_gpkg_layer(polys_gpkg_path,  polys_layer_name,  QgsWkbTypes.Polygon,  f_poly)

    return points_src, lines_src, polys_src



def do(dtm, dsm, corr, high_mask, sep, debug = True):
    """
        splits centerline linestrings into high/low segments
        (based on a polygon mask)
        
        inputs:
            raster DTM
            raster DSM
            vector linestrings of corridor definition
            vector polygon mask defining high/low areas
            separation gap
            debug = true outputs all intermediate layers to canvas
        
        outputs:
            point3d sets for edges of corridors
            line2d segments to be used as delaunay triangulation breaklines
    """

    from .out_helpers import _temp_vector
    
    path_vector_pass_centerlines = _temp_vector("acm4_passCL")
    path_vector_nopass_centerlines = _temp_vector("acm4_nopassCL")
    path_vector_high_centerlines = _temp_vector("acm4_highCL")
    path_vector_low_centerlines = _temp_vector("acm4_lowCL")
    path_vector_corr_points_low = _temp_vector("acm4_corr_pnts_low")
    path_vector_corr_lines_low = _temp_vector("acm4_corr_lines_low")
    path_vector_corr_poly_low = _temp_vector("acm4_corr_poly_low")
    path_vector_corr_points_high = _temp_vector("acm4_corr_pnts_high")
    path_vector_corr_lines_high = _temp_vector("acm4_corr_lines_high")
    path_vector_corr_poly_high = _temp_vector("acm4_corr_poly_high")
    path_vector_ground_centerlines = _temp_vector("acm4_corr_groundCL")
    path_vector_ground_CL_single = _temp_vector("acm4_corr_groundCLsingle")
    path_vector_raised_CL_single = _temp_vector("acm4_corr_raisedCLsingle")


    # Initialize the actual layers inside those files
    points_src_low, lines_src_low, poly_src_low = init_corridor_output_layers(
        points_gpkg_path=path_vector_corr_points_low,
        lines_gpkg_path=path_vector_corr_lines_low,
        polys_gpkg_path=path_vector_corr_poly_low,
        points_layer_name="points3d",
        lines_layer_name="breaklines",
        polys_layer_name="corridors"
    )

    points_src_high, lines_src_high, poly_src_high = init_corridor_output_layers(
        points_gpkg_path=path_vector_corr_points_high,
        lines_gpkg_path=path_vector_corr_lines_high,
        polys_gpkg_path=path_vector_corr_poly_high,
        points_layer_name="points3d",
        lines_layer_name="breaklines",
        polys_layer_name="corridors"
    )

    
    # split linestrings overpass / groundlevel linestrings
    
    result = processing.run("native:extractbyattribute",
        {
            "INPUT": corr,
            "FIELD": "passover",
            "OPERATOR": 0,
            "VALUE": 1,
            "OUTPUT": path_vector_pass_centerlines
        }
    )
    result = processing.run("native:extractbyattribute",
        {
            "INPUT": corr,
            "FIELD": "passover",
            "OPERATOR": 0,
            "VALUE": 0,
            "OUTPUT": path_vector_nopass_centerlines
        }
    )

    # split overpass linestrings by high poly mask
    
    result = processing.run("native:intersection",
        {
            "INPUT": path_vector_pass_centerlines,
            "OVERLAY": high_mask,
            "INPUT_FIELDS": [],              
            "OVERLAY_FIELDS": None, 
            "GRID_SIZE": 0.001,    
            "OUTPUT": path_vector_high_centerlines   
        }
    )

    result = processing.run("native:difference",
        {
            "INPUT": path_vector_pass_centerlines,
            "OVERLAY": high_mask,
            "OUTPUT": path_vector_low_centerlines
        }
    )

    # combine lowpass and nopass linestring layers
    
    result = processing.run("native:mergevectorlayers",
        {
            "LAYERS": [
                path_vector_nopass_centerlines,
                path_vector_low_centerlines
            ],
            "CRS": None,
            "OUTPUT": path_vector_ground_centerlines
        }
    )

    # ensure linestrings are single not multi

    result_singleparts = processing.run("native:multiparttosingleparts",
        {
            "INPUT": path_vector_ground_centerlines,
            "OUTPUT": path_vector_ground_CL_single
        }
    )
    result_singleparts = processing.run("native:multiparttosingleparts",
        {
            "INPUT": path_vector_high_centerlines,
            "OUTPUT": path_vector_raised_CL_single
        }
    )

    # corridor build
    
    (
        path_vector_corr_points_low, 
        path_vector_corr_lines_low, 
        path_vector_corr_poly_low
    ) = run_corridor_wrapper_paths(
        centerline_layer_path = path_vector_ground_CL_single,
        raster_path = dtm,
        separation = sep,
        points3d_layer_path = points_src_low,
        lines2d_layer_path = lines_src_low,
        polygon_layer_path = poly_src_low,
        default_width = 8.0,
        default_type = "road",
        dtm_band = 1
    )

    (
        path_vector_corr_points_high, 
        path_vector_corr_lines_high, 
        path_vector_corr_poly_high
    ) = run_corridor_wrapper_paths(
        centerline_layer_path = path_vector_raised_CL_single,
        raster_path = dsm,
        separation = sep,
        points3d_layer_path = points_src_high,
        lines2d_layer_path = lines_src_high,
        polygon_layer_path = poly_src_high,
        default_width = 8.0,
        default_type = "road",
        dtm_band = 1
    )

    

    if debug:
        from .out_helpers import add_vector

        _ = add_vector(path_vector_pass_centerlines, "5-Corridor - Pass Centerlines")
        _ = add_vector(path_vector_nopass_centerlines, "5-Corridor - NoPass Centerlines")
        _ = add_vector(path_vector_high_centerlines, "5-Corridor - HighPass Centerlines")
        _ = add_vector(path_vector_low_centerlines, "5-Corridor - LowPass Centerlines")
        _ = add_vector(path_vector_corr_points_low, "5-Corridor - LowPass Points 3d")
        _ = add_vector(path_vector_corr_lines_low, "5-Corridor - LowPass Breaklines")
        _ = add_vector(path_vector_corr_poly_low, "5-Corridor - LowPass PolyMask")
        _ = add_vector(path_vector_corr_points_high, "5-Corridor - HighPass Points 3d")
        _ = add_vector(path_vector_corr_lines_high, "5-Corridor - HighPass Breaklines")
        _ = add_vector(path_vector_corr_poly_high, "5-Corridor - HighPass PolyMask")
        _ = add_vector(path_vector_ground_CL_single, "5-Corridor - Ground Centerlines")
        _ = add_vector(path_vector_raised_CL_single, "5-Corridor - Raised Centerlines")


  
    return (
        path_vector_corr_points_low,
        path_vector_corr_lines_low,
        path_vector_corr_poly_low,
        path_vector_corr_points_high,
        path_vector_corr_lines_high,
        path_vector_corr_poly_high
    )
        
        
    
# -------------------------
# Corridors Helpers
# -------------------------

# -------------------------
# Wrapper
# -------------------------

from typing import List, Tuple, Optional
from qgis.core import (
    QgsVectorLayer, QgsRasterLayer, QgsProject, QgsWkbTypes,
    QgsFeature, QgsGeometry, QgsPointXY, QgsCoordinateTransform,
    QgsVectorFileWriter, QgsFields, QgsField
)
from qgis.PyQt.QtCore import QVariant

def run_corridor_wrapper_paths(
    centerline_layer_path: str,
    raster_path: str,
    separation: float,
    points3d_layer_path: str,
    lines2d_layer_path: str,
    polygon_layer_path: str,
    default_width: float = 8.0,
    default_type: str = "road",
    dtm_band: int = 1
) -> Tuple[str, str, str]:
    """
    Batch wrapper around build_corridor_products() using file paths.

    Inputs
    ------
    centerline_layer_path : str
        Path to a line vector layer (e.g., 'C:/data.gpkg|layername=centerlines')
    raster_path           : str
        Path to DTM raster (e.g., 'C:/dtm.tif')
    separation            : float
        Offset densify spacing (map units)
    points3d_layer_path   : str
        Path to existing file‑backed PointZ layer (will append)
    lines2d_layer_path    : str
        Path to existing file‑backed LineString layer (will append)
    polygon_layer_path    : str
        Path to existing file‑backed Polygon layer (will append)
    default_width         : float
        Fallback width if 'width' attribute missing
    default_type          : str
        Fallback type if 'type' attribute missing
    dtm_band              : int
        Raster band for Z sampling

    Returns
    -------
    (points3d_layer_path, lines2d_layer_path, polygon_layer_path)
    """

    # --- Load inputs ---
    cl_layer = _load_vector_layer_from_path(centerline_layer_path, "centerlines_src")
    dtm_layer = _load_raster_from_path(raster_path, "dtm_src")

    # Expect line geometry for centerlines
    _expect_geometry(cl_layer, QgsWkbTypes.LineGeometry, label="centerline layer")

    # Load outputs (must be file‑backed; this opens the existing layers)
    ptsL = _load_vector_layer_from_path(points3d_layer_path, "points3d_out")
    lnsL = _load_vector_layer_from_path(lines2d_layer_path, "lines2d_out")
    plyL = _load_vector_layer_from_path(polygon_layer_path, "polygon_out")

    # Expect Point geometry for points layer and Z‑enabled
    _expect_geometry(ptsL, QgsWkbTypes.PointGeometry, require_z=True, label="points3d_layer")
    # Expect Line geometry for lines layer (2D is fine)
    _expect_geometry(lnsL, QgsWkbTypes.LineGeometry, label="lines2d_layer")
    # Expect Polygon geometry for polygon layer (2D is fine)
    _expect_geometry(plyL, QgsWkbTypes.PolygonGeometry, label="polygon_layer")

    # Ensure polygon 'type' field exists
    poly_provider = plyL.dataProvider()
    if "type" not in [f.name() for f in plyL.fields()]:
        poly_provider.addAttributes([QgsField("type", QVariant.String)])
        plyL.updateFields()

    pts_provider = ptsL.dataProvider()
    lns_provider = lnsL.dataProvider()

    project = QgsProject.instance()
    project_crs = project.crs()
    cl_crs = cl_layer.crs()

    # Pre‑check attribute names present in centerline layer
    cl_field_names = [f.name() for f in cl_layer.fields()]
    has_width = "width" in cl_field_names
    has_type = "type" in cl_field_names

    # --- Iterate features ---
    for feat in cl_layer.getFeatures():
        geom = feat.geometry()
        # Transform centerline to project CRS for geometric ops in build_corridor_products
        if cl_crs != project_crs:
            geom = QgsGeometry(geom)  # copy for transform
            geom.transform(QgsCoordinateTransform(cl_crs, project_crs, project))

        width_val = _num_or_default(feat["width"], default_width) if has_width else float(default_width)
        type_val = str(feat["type"]) if has_type and feat["type"] not in [None, ""] else default_type

        # Call your existing core builder (assumes build_corridor_products is already defined in scope)


        z_sample_mode = 0
        if "z_sample" in cl_layer.fields().names():
            try:
                z_sample_mode = int(feat["z_sample"])
            except Exception:
                z_sample_mode = 0

        mpz_geom, breaklines_geom, poly_geom = build_corridor_products(
            centerline2d=geom,
            dtm_raster=dtm_layer,
            width=float(width_val),
            separation=float(separation),
            dtm_band=dtm_band,
            z_sample_mode=z_sample_mode        # <— pass through
        )

        # --- Append PointZs as individual features ---
        pt_feats = []
        vit = mpz_geom.vertices()  # yields QgsPoint (with Z)
        i = 1
        while vit.hasNext():
            p = vit.next()
            f = QgsFeature(ptsL.fields())
            f.setGeometry(QgsGeometry.fromPoint(p))  # preserves Z
            # Add optional id if the target has it; otherwise skip
            if "pid" in [fld.name() for fld in ptsL.fields()]:
                f["pid"] = i
            pt_feats.append(f)
            i += 1
        if pt_feats:
            pts_provider.addFeatures(pt_feats)

        # --- Append breakline segments as individual LineString features ---
        segs = breaklines_geom.asMultiPolyline()  # List[List[QgsPointXY]]
        ln_feats = []
        for seg in segs:
            lf = QgsFeature(lnsL.fields())
            lf.setGeometry(QgsGeometry.fromPolylineXY(seg))
            ln_feats.append(lf)
        if ln_feats:
            lns_provider.addFeatures(ln_feats)

        # --- Append polygon, carrying 'type' attribute ---
        pf = QgsFeature(plyL.fields())
        pf.setGeometry(poly_geom)
        if "type" in [fld.name() for fld in plyL.fields()]:
            pf["type"] = type_val
        poly_provider.addFeatures([pf])

    # Update extents
    ptsL.updateExtents()
    lnsL.updateExtents()
    plyL.updateExtents()

    # Return the same paths
    return points3d_layer_path, lines2d_layer_path, polygon_layer_path


# -------------------------
# Main Calc
# -------------------------

from typing import Tuple, List, Optional
import math
from qgis.core import (
    QgsGeometry,
    QgsRasterLayer,
    QgsProject,
    QgsCoordinateTransform,
    QgsWkbTypes,
    QgsPoint,
    QgsPointXY,
)

from typing import Tuple, List, Optional
import math
from qgis.core import (
    QgsGeometry,
    QgsRasterLayer,
    QgsProject,
    QgsCoordinateTransform,
    QgsWkbTypes,
    QgsPoint,
    QgsPointXY,
)

def build_corridor_products(
    centerline2d: QgsGeometry,
    dtm_raster: QgsRasterLayer,
    width: float,
    separation: float,
    *,
    dtm_band: int = 1,
    z_sample_mode: int = 0    # <— NEW: 0=centerline, 1=edge
) -> Tuple[QgsGeometry, QgsGeometry, QgsGeometry]:
    """
    Construct corridor boundary and derived products in pure PyQGIS.

    Returns:
        multipointZ : MultiPointZ (boundary vertices with Z sampled per z_sample_mode)
        breaklines_mls : MultiLineString (2-vertex segments around the boundary ring)
        polygon2d : Polygon (2D corridor polygon)

    Parameters:
        centerline2d : 2D line geometry (single or multi)
        dtm_raster   : DEM/DTM raster to sample elevations from
        width        : corridor total width (map units)
        separation   : vertex spacing used when densifying offsets
        dtm_band     : raster band index for sampling
        z_sample_mode:
            0 -> sample Z at nearest XY on centerline (original behaviour)
            1 -> sample Z at actual boundary vertex XY (edge mode)
    """

    # -------- Guards --------
    if centerline2d is None or centerline2d.isEmpty():
        raise ValueError("centerline2d is empty.")
    if dtm_raster is None or not isinstance(dtm_raster, QgsRasterLayer) or not dtm_raster.isValid():
        raise ValueError("dtm_raster must be a valid QgsRasterLayer.")
    if width <= 0:
        raise ValueError("width must be > 0.")
    if separation <= 0:
        raise ValueError("separation must be > 0.")


    # --------- separation check -----------
    if separation > width:
        separation = width



    # -------- Normalize centerline to a simple LineString --------
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

    # -------- Offsets --------
    half_w = width / 2.0
    segments = 2  # increase for rounder corners
    join_style = QgsGeometry.JoinStyleRound
    miter_limit = 2.0

    left = cl.offsetCurve(+half_w, segments, join_style, miter_limit)
    right = cl.offsetCurve(-half_w, segments, join_style, miter_limit)
    if left.isEmpty() or right.isEmpty():
        raise RuntimeError("Offset curve failed (check geometry validity and width).")

    # -------- Densify offsets --------
    left_d = left.densifyByDistance(separation)
    right_d = right.densifyByDistance(separation)

    left_pts = _line_to_points_xy(left_d)
    right_pts = _line_to_points_xy(right_d)
    if len(left_pts) < 2 or len(right_pts) < 2:
        raise RuntimeError("Densification produced too few points; adjust separation or input geometry.")

    # -------- Boundary ring (reverse the right edge and close) --------
    right_pts.reverse()
    boundary_ring: List[QgsPointXY] = left_pts + right_pts
    if not boundary_ring:
        raise RuntimeError("Boundary ring construction failed (no points).")
    if boundary_ring[0] != boundary_ring[-1]:
        boundary_ring.append(boundary_ring[0])

    # -------- Breaklines: 2-vertex segments around the ring --------
    segs_mls: List[List[QgsPointXY]] = []
    for i in range(len(boundary_ring) - 1):
        a = boundary_ring[i]
        b = boundary_ring[i + 1]
        segs_mls.append([a, b])
    breaklines_mls = QgsGeometry.fromMultiPolylineXY(segs_mls)

    # -------- Polygon from boundary --------
    polygon2d = QgsGeometry.fromPolygonXY([boundary_ring])

    # -------- Raster sampling setup --------
    project_crs = QgsProject.instance().crs()
    raster_crs = dtm_raster.crs()
    try:
        xform = QgsCoordinateTransform(project_crs, raster_crs, QgsProject.instance()) if project_crs != raster_crs else None
    except Exception:
        xform = None

    provider = dtm_raster.dataProvider()
    nodata_val = provider.sourceNoDataValue(dtm_band)  # may be 0.0, NaN, or None

    def _unwrap_sample_value(v) -> Optional[float]:
        # Accepts scalar, (value, ok), [value, ok], QVariant-like; returns float or None
        if v is None:
            return None
        if isinstance(v, (tuple, list)):
            v = v[0] if v else None
        try:
            if hasattr(v, "isNull") and v.isNull():
                return None
            if hasattr(v, "toDouble"):
                dv, ok = v.toDouble()
                return float(dv) if ok else None
        except Exception:
            pass
        try:
            vf = float(v)
            if math.isnan(vf):
                return None
            return vf
        except Exception:
            return None

    def _sample_filtered(xy: QgsPointXY) -> Optional[float]:
        """Sample and treat explicit NoData as missing; returns float or None."""
        try:
            raw = provider.sample(xy, dtm_band)
        except Exception:
            return None
        val = _unwrap_sample_value(raw)
        if val is None:
            return None
        # Treat NoData as None
        if nodata_val is not None:
            try:
                if (isinstance(nodata_val, float) and math.isnan(nodata_val)) and math.isnan(val):
                    return None
                if val == nodata_val:
                    return None
            except Exception:
                pass
        return val

    # -------- Sample Z for each boundary vertex (respects z_sample_mode) --------
    #   0 -> sample at nearest XY on centerline, fallback to boundary XY
    #   1 -> sample at boundary XY only (no centreline usage)
    z_points: List[QgsPoint] = []

    # Clamp/validate z_sample_mode quietly
    z_mode = 1 if int(z_sample_mode) == 1 else 0

    for pt in boundary_ring[:-1]:  # exclude duplicated closing vertex
        if z_mode == 1:
            # EDGE MODE: sample at perimeter vertex XY
            sample_xy = QgsPointXY(pt.x(), pt.y())
        else:
            # CENTERLINE MODE: nearest centerline XY in project CRS
            nearest_pt = cl.nearestPoint(QgsGeometry.fromPointXY(pt)).asPoint()
            sample_xy = QgsPointXY(nearest_pt.x(), nearest_pt.y())

        # Transform to raster CRS if needed
        sample_xy_r = sample_xy
        if xform:
            try:
                sample_xy_r = xform.transform(sample_xy)
            except Exception:
                pass

        # Primary sample
        z_val: Optional[float] = None
        if dtm_raster.extent().contains(sample_xy_r):
            z_val = _sample_filtered(sample_xy_r)

        if z_val is None:
            if z_mode == 0:
                # In centreline mode, fallback to boundary vertex XY (transformed)
                alt_xy = pt
                if xform:
                    try:
                        alt_xy = xform.transform(pt)
                    except Exception:
                        pass
                if dtm_raster.extent().contains(alt_xy):
                    z_val = _sample_filtered(alt_xy)
            else:
                # In edge mode, never touch the centreline; hard fallback to 0.0
                z_val = 0.0

        if z_val is None:
            z_val = 0.0

        z_points.append(QgsPoint(pt.x(), pt.y(), z_val))

    # -------- Build MultiPointZ robustly --------
    multipointZ = _make_multipoint_z(z_points)
    if multipointZ.isEmpty():
        raise RuntimeError("Failed to construct MultiPointZ geometry from raster-sampled points.")
    assert QgsWkbTypes.isMultiType(multipointZ.wkbType()), "Multipoint is not multi"
    assert QgsWkbTypes.hasZ(multipointZ.wkbType()), "Multipoint is not Z-enabled"

    return multipointZ, breaklines_mls, polygon2d





# -------------------------
# Helpers
# -------------------------
    
def _load_vector_layer_from_path(path: str, name: str) -> QgsVectorLayer:
    vl = QgsVectorLayer(path, name, "ogr")
    if not vl.isValid():
        raise RuntimeError(f"Failed to load vector layer: {path}")
    return vl

def _load_raster_from_path(path: str, name: str = "dtm") -> QgsRasterLayer:
    rl = QgsRasterLayer(path, name)
    if not rl.isValid():
        raise RuntimeError(f"Failed to load raster layer: {path}")
    return rl

def _expect_geometry(vl: QgsVectorLayer, geom_type: int, require_z: Optional[bool] = None, label: str = "layer"):
    wkb = vl.wkbType()
    if QgsWkbTypes.geometryType(wkb) != geom_type:
        raise TypeError(f"{label} must be {QgsWkbTypes.displayString(geom_type)}, got {QgsWkbTypes.displayString(wkb)}")
    if require_z is not None:
        has_z = QgsWkbTypes.hasZ(wkb)
        if require_z and not has_z:
            raise TypeError(f"{label} must be Z‑enabled (PointZ/LineStringZ/PolygonZ). Got: {QgsWkbTypes.displayString(wkb)}")

def _num_or_default(val, default_val: float) -> float:
    try:
        if val is None:
            return float(default_val)
        return float(val)
    except Exception:
        return float(default_val)

def _line_to_points_xy(g: QgsGeometry) -> List[QgsPointXY]:
    """Extract a flat list of QgsPointXY from a LineString or MultiLineString geometry."""
    if g is None or g.isEmpty():
        return []
    if g.isMultipart():
        m = g.asMultiPolyline()  # List[List[QgsPoint]]
        pts: List[QgsPointXY] = []
        for seg in m:
            for p in seg:
                pts.append(QgsPointXY(p))
        return pts
    else:
        pl = g.asPolyline()  # List[QgsPoint]
        return [QgsPointXY(p) for p in pl] if pl else []

def _unwrap_sample_value(v) -> Optional[float]:
    """
    Raster providers in QGIS 3.x can return:
      - float
      - None
      - (value, ok) tuple
      - [value, ok] list
      - QVariant-like objects
    Normalize to a float or None.
    """
    if v is None:
        return None
    # Unwrap tuple/list like (value, ok)
    if isinstance(v, (tuple, list)):
        v = v[0] if v else None
    # QVariant-like guards
    try:
        if hasattr(v, "isNull") and v.isNull():
            return None
        if hasattr(v, "toDouble"):
            dv, ok = v.toDouble()
            return float(dv) if ok else None
    except Exception:
        pass
    # Convert to float and filter NaN
    try:
        vf = float(v)
        if math.isnan(vf):
            return None
        return vf
    except Exception:
        return None

def _sample_raster_value(provider, xy: QgsPointXY, band: int) -> Optional[float]:
    """Sample a raster value from provider at xy, robust across provider return types."""
    try:
        raw = provider.sample(xy, band)
    except Exception:
        return None
    return _unwrap_sample_value(raw)

def _make_multipoint_z(points: List[QgsPoint]) -> QgsGeometry:
    """
    Robust MultiPointZ creator for QGIS 3.44:
    Accepts a list of QgsPoint (with Z) and returns a MultiPointZ geometry via WKT.
    """
    if not points:
        return QgsGeometry()  # empty
    # Use inner parentheses for maximal WKT compatibility.
    coords = ", ".join(f"({p.x()} {p.y()} {p.z()})" for p in points)
    wkt = f"MULTIPOINT Z ({coords})"
    return QgsGeometry.fromWkt(wkt)