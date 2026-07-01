# acm4/raster_prep.py

from qgis.core import (
    QgsProject, QgsRasterLayer, QgsProcessingUtils, QgsMessageLog, Qgis
)
import processing
import os
from pathlib import Path

def _temp_raster(name: str) -> str:
    """Create a deterministic temp filename with .tif in QGIS temp folder."""
    # QGIS temp folder (per session); ensure .tif extension for GDAL
    base = Path(QgsProcessingUtils.tempFolder()) / f"{name}.tif"
    return str(base)

def _log(msg: str):
    QgsMessageLog.logMessage(msg, "acm4", Qgis.Info)

def do(dtm, dsm, ext,
       offset=10, nodata=-9999,
       crop=True, keep_res=True,
       debug=True):
    """
    Clips DTM and DSM using a healed offset cutline built by geom_helpers.
    Returns (path_raster_dtm, path_raster_dsm, path_raster_ndsm, path_raster_slope)
    """
    # 1) Resolve one AOI feature
    feat = next(ext.getFeatures(), None)
    if feat is None:
        raise ValueError("EXTENT layer has no features.")
    aoi_geom = feat.geometry()
    crs_authid = ext.crs().authid()

    # 2) Build healed offset + persisted mask file
    from .geom_helpers import get_offset_mask
    offset_geom, path_mask_clip = get_offset_mask(
        aoi_geom=aoi_geom,
        offset=offset,
        crs_authid=crs_authid,
        persist_to_gpkg=True,
        heal=True,
        segments=8
    )
    _log(f"[acm4] path_mask_clip={path_mask_clip} exists={os.path.exists(path_mask_clip)}")

    # 3) Explicit output paths (no TEMPORARY_OUTPUT ambiguity)
    path_raster_dtm = _temp_raster("acm4_dtm_clip")
    path_raster_dsm = _temp_raster("acm4_dsm_clip")
    path_raster_ndsm = _temp_raster("acm4_ndsm")
    path_raster_slope = _temp_raster("acm4_slope")
    path_raster_aspect = _temp_raster("acm4_aspect")

    # --- DTM clip ---
    res_dtm = processing.run("gdal:cliprasterbymasklayer", 
        {
            "INPUT": dtm,
            "MASK": path_mask_clip,
            "NODATA": nodata,
            "CROP_TO_CUTLINE": crop,
            "KEEP_RESOLUTION": keep_res,
            "OUTPUT": path_raster_dtm,
            "OPTIONS": "COMPRESS=NONE",
        }
    )
    
    _log(f"[acm4] path_raster_dtm={path_raster_dtm} exists={os.path.exists(path_raster_dtm)} size={os.path.getsize(path_raster_dtm) if os.path.exists(path_raster_dtm) else 0}")
    # Validate the raster can be opened
    dtm_test = QgsRasterLayer(path_raster_dtm, "DTM (clipped)")
    if not dtm_test.isValid():
        raise ValueError(f"DTM clipped invalid. path={path_raster_dtm}")

    # --- DSM clip ---
    res_dsm = processing.run("gdal:cliprasterbymasklayer", 
        {
            "INPUT": dsm,
            "MASK": path_mask_clip,
            "NODATA": nodata,
            "CROP_TO_CUTLINE": crop,
            "KEEP_RESOLUTION": keep_res,
            "OUTPUT": path_raster_dsm,
            "OPTIONS": "COMPRESS=NONE",
        }
    )
    _log(f"[acm4] path_raster_dsm={path_raster_dsm} exists={os.path.exists(path_raster_dsm)} size={os.path.getsize(path_raster_dsm) if os.path.exists(path_raster_dsm) else 0}")
    dsm_test = QgsRasterLayer(path_raster_dsm, "DSM (clipped)")
    if not dsm_test.isValid():
        raise ValueError(f"DSM clipped invalid. path={path_raster_dsm}")

    # 4) nDSM = DSM - DTM  (explicit output path & type)
    res_ndsm = processing.run("gdal:rastercalculator", 
        {
            "INPUT_A": path_raster_dsm, "BAND_A": 1,
            "INPUT_B": path_raster_dtm, "BAND_B": 1,
            "INPUT_C": None, "BAND_C": -1,
            "INPUT_D": None, "BAND_D": -1,
            "INPUT_E": None, "BAND_E": -1,
            "INPUT_F": None, "BAND_F": -1,
            "FORMULA": "A - B",
            "NO_DATA": -9999,
            "RTYPE": 5,                   # Float32
            "OUTPUT": path_raster_ndsm,
            "OPTIONS": "COMPRESS=NONE",
        }
    )
    _log(f"[acm4] path_raster_ndsm={path_raster_ndsm} exists={os.path.exists(path_raster_ndsm)} size={os.path.getsize(path_raster_ndsm) if os.path.exists(path_raster_ndsm) else 0}")
    ndsm_test = QgsRasterLayer(path_raster_ndsm, "nDSM (clipped)")
    if not ndsm_test.isValid():
        raise ValueError(f"nDSM invalid. path={path_raster_ndsm}")

    # 5) run slope analysis
    # res_sac = processing.run("sagang:slopeaspectcurvature",
        # {
            # "ELEVATION": path_raster_dtm,
            # "METHOD": 0,
            # "UNIT_SLOPE": 1,
            # "UNIT_ASPECT": 1,
            # "SLOPE": path_raster_slope,
            # "ASPECT": path_raster_aspect,
            # "C_GENERAL": None,
            # "C_PROFILE": None,
            # "C_PLAN": None,
            # "C_TANGENTIAL": None,
            # "C_LONGITUDINAL": None,
            # "C_CROSSSECTIONAL": None,
            # "C_MINIMAL": None,
            # "C_MAXIMAL": None,
            # "C_FLOW": None
        # }
    # )


    res_sac = processing.run("grass:r.slope.aspect",
        {
            "elevation": path_raster_dtm,

            # choose any subset you need:
            "slope": path_raster_slope,
            #"aspect": out_aspect,
            #"pcurvature": out_pcurv,
            #"tcurvature": out_tcurv,

            # options
            "format": 0,          # 0=degrees, 1=percent (for "slope")
            "precision": 0,       # 0=FCELL (float32), 1=DCELL (float64), 2=CELL (int)

            # parameters
            "zscale": 1.0,
            "min_slope": 0.0,
            "nprocs": 0,          # 0=auto; or an integer for threads

            # region/extent & cellsize (let QGIS/GRASS infer from input)
            "GRASS_REGION_PARAMETER": None,
            "GRASS_REGION_CELLSIZE_PARAMETER": 0,

            # leave unused derivatives unset
            "dx": None, "dy": None, "dxx": None, "dyy": None, "dxy": None,

            # misc
            "GRASS_SNAP_TOLERANCE_PARAMETER": -1,
            "GRASS_MIN_AREA_PARAMETER": 0.0001,
            # flags are added via "flags": "..." if needed (see below)
        }
    )


    slope_test = QgsRasterLayer(path_raster_slope, "Slope")
    if not slope_test.isValid():
        raise ValueError(f"Slope invalid. path={path_raster_slope}")
        
        
    if debug:
        from .out_helpers import add_raster

        _ = add_raster(path_raster_dtm, "1-RasterPrep - DTM (clipped)")
        _ = add_raster(path_raster_dsm, "1-RasterPrep - DSM (clipped)")
        _ = add_raster(path_raster_ndsm, "1-RasterPrep - nDSM (clipped)")
        _ = add_raster(path_raster_slope, "1-RasterPrep - DTM (slope)")

    return path_raster_dtm, path_raster_dsm, path_raster_ndsm, path_raster_slope, path_mask_clip