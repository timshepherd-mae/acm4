# acm4/ndsm_mask.py

from qgis.core import (
    QgsProject, QgsRasterLayer, QgsProcessingUtils, QgsMessageLog, Qgis
)
import processing
import os
from pathlib import Path

def do(path_ndsm, zdiff_thresh, oversize, debug = True):
    """
        create mask layer where nDSM values are greater than
        threshold value to ascertain Above Ground elements.
        clean raster result and polygonise.
        
        inputs:
            raster nDSM
            number (float) zdiff threshold
            debug = true outputs all intermediate layers to canvas
        
        outputs:
            polygon mask for AboveGround areas
    """

    from .out_helpers import _temp_raster, _temp_vector
    
    path_raster_mask_ndsm = _temp_raster("acm4_ndsm_mask")
    path_raster_mask_erode = _temp_raster("acm4_ndsm_erode")
    path_raster_mask_dilate = _temp_raster("acm4_ndsm_dilate")
    path_vector_poly_ndsm = _temp_vector("acm4_poly_ndsms")
    path_vector_poly_high = _temp_vector("acm4_poly_high")
    path_vector_poly_high_smooth = _temp_vector("acm4_poly_high_smooth")
    tmpr = _temp_raster("tmpr")
    tmpv = _temp_vector("tmpv")

    
    # 1) mask by zDiff
    
    formula = f"(A >= {zdiff_thresh}) * 1"
    res_slopemask = processing.run("gdal:rastercalculator", 
        {
            "INPUT_A": path_ndsm, "BAND_A": 1,
            "INPUT_B": None, "BAND_B": -1,
            "INPUT_C": None, "BAND_C": -1,
            "INPUT_D": None, "BAND_D": -1,
            "INPUT_E": None, "BAND_E": -1,
            "INPUT_F": None, "BAND_F": -1,
            "FORMULA": formula,
            "NO_DATA": -9999,
            "RTYPE": 5,                   # Float32
            "OUTPUT": path_raster_mask_ndsm,
            "OPTIONS": "COMPRESS=NONE",
        }
    )

    # 2) morph erode then dilate 
    
    # result = processing.run("sagang:morphologicalfilter",
        # {
            # "INPUT": path_raster_mask_ndsm,
            # "METHOD": 1,
            # "KERNEL_TYPE": 1,
            # "RADIUS": 2,
            # "RESULT": path_raster_mask_erode
        # }
    # )
    # result = processing.run("sagang:morphologicalfilter",
        # {
            # "INPUT": path_raster_mask_erode,
            # "METHOD": 0,
            # "KERNEL_TYPE": 1,
            # "RADIUS": 1,
            # "RESULT": path_raster_mask_dilate
        # }
    # )
    processing.run("grass:r.neighbors",
        {
            "input": path_raster_mask_ndsm,
            "method":  "minimum",
            "size": 5,                # window size in cells (odd number)
            "output": tmpr,
            "GRASS_REGION_PARAMETER": None,
            "GRASS_REGION_CELLSIZE_PARAMETER": 0
        }
    )
    processing.run("grass:r.neighbors",
        {
            "input": tmpr,
            "method":  "maximum",
            "size": 5,                # window size in cells (odd number)
            "output": path_raster_mask_dilate,
            "GRASS_REGION_PARAMETER": None,
            "GRASS_REGION_CELLSIZE_PARAMETER": 0
        }
    )




    # 3) polygonise clean ndsm mask
    
    result = processing.run("gdal:polygonize",
        {
            "INPUT": path_raster_mask_dilate,
            "BAND": 1,
            "FIELD": "DN",
            "EIGHT_CONNECTEDNESS": False,
            "EXTRA": "",
            "OUTPUT": tmpv 
        }
    )

    # 4) Buffer polygon
    
    result = processing.run("native:buffer",
        {
            "INPUT": tmpv,
            "DISTANCE": oversize,
            "SEGMENTS": 5,
            "END_CAP_STYLE": 0,
            "JOIN_STYLE": 0,
            "MITER_LIMIT": 2,
            "DISSOLVE": False,
            "OUTPUT": path_vector_poly_ndsm
        }
    )

    # 5) Extract high polys

    formula = f"\"DN\" = 1"
    result = processing.run("native:extractbyexpression",
        {
            "INPUT": path_vector_poly_ndsm,
            "EXPRESSION": formula,
            "OUTPUT": tmpv
        }
    )
    result = processing.run("native:dissolve",
        {
            "INPUT": tmpv,
            "FIELD": [], 
            "SEPARATE_DISJOINT": False,
            "OUTPUT": path_vector_poly_high
        }
    )

    
    # 6) Smooth the polygon
    
    result = processing.run("native:smoothgeometry",
        {
            "INPUT": path_vector_poly_high,
            "ITERATIONS": 2,                # 1–5 typical
            "OFFSET": 0.5,                 # 0.1–0.5 recommended
            "MAX_ANGLE": 180,               # keep full smoothing
            "OUTPUT": path_vector_poly_high_smooth
        }
    )




    if debug:
        from .out_helpers import add_vector, add_raster

        _ = add_raster(path_raster_mask_ndsm, "4-nDSM Mask - Threshold Mask")
        #_ = add_raster(path_raster_mask_erode, "4-nDSM Mask - Threshold Mask Eroded")
        _ = add_raster(path_raster_mask_dilate, "4-nDSM Mask - Threshold Mask Dilated")
        _ = add_vector(path_vector_poly_ndsm, "4-nDSM Mask - High/Low Polygons")
        _ = add_vector(path_vector_poly_high, "4-nDSM Mask - High Polygon")
        _ = add_vector(path_vector_poly_high_smooth, "4-nDSM Mask - High Polygon Smoothed")


    return path_vector_poly_high_smooth
