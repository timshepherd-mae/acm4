# acm4/slope_mask.py

from qgis.core import (
    QgsProject, QgsRasterLayer, QgsProcessingUtils, QgsMessageLog, Qgis
)
import processing
import os
from pathlib import Path



def _log(msg: str):
    QgsMessageLog.logMessage(msg, "acm4", Qgis.Info)



def do(slopemap, slopelimit, clipmask, debug = True):
    """
        masks the slopemap with a threshold slope value (in degrees)
        polygonise the mask, cull small polygons,
        returns 2 output polygon layers (one each for steep and shallow)
    """

    from .out_helpers import _temp_raster, _temp_vector
    
    path_raster_slopemask = _temp_raster("acm4_slope_mask")
    path_raster_slopeopen = _temp_raster("acm4_slope_open")
    path_vector_slopepoly = _temp_vector("acm4_slope_poly")
    path_vector_steeppoly_holes = _temp_vector("acm4_steep_poly_holes")
    path_vector_steeppoly_noholes = _temp_vector("acm4_steep_poly_noholes")
    path_vector_bufferout = _temp_vector("acm4_bufferout")
    path_vector_steeppoly = _temp_vector("acm4_steeppoly")
    path_vector_shallowpoly = _temp_vector("acm4_shallowpoly")
    tmp = _temp_raster("acm4_tmp")


    # 1) mask by slope limit
    
    formula = f"(A >= {slopelimit}) * 1"
    res_slopemask = processing.run("gdal:rastercalculator", 
        {
            "INPUT_A": slopemap, "BAND_A": 1,
            "INPUT_B": None, "BAND_B": -1,
            "INPUT_C": None, "BAND_C": -1,
            "INPUT_D": None, "BAND_D": -1,
            "INPUT_E": None, "BAND_E": -1,
            "INPUT_F": None, "BAND_F": -1,
            "FORMULA": formula,
            "NO_DATA": -9999,
            "RTYPE": 5,                   # Float32
            "OUTPUT": path_raster_slopemask,
            "OPTIONS": "COMPRESS=NONE",
        }
    )
    slopemask_test = QgsRasterLayer(path_raster_slopemask, "Slopemask")
    if not slopemask_test.isValid():
        raise ValueError(f"Slopemask invalid. path={path_raster_slopemask}")


    # 2) morph opening 
    
    # result = processing.run(
        # "sagang:morphologicalfilter",
        # {
            # "INPUT": path_raster_slopemask,
            # "METHOD": 2,
            # "KERNEL_TYPE": 1,
            # "RADIUS": 2,
            # "RESULT": path_raster_slopeopen
        # }
    # )

    # processing.run("gdal:neighbours",
        # {
            # "INPUT": path_raster_slopemask,
            # "RADIUS": 2,
            # "STATS": 0,     # MIN (erosion)
            # "OUTPUT": tmp
        # }
    # )
    # processing.run("gdal:neighbours",
        # {
            # "INPUT": tmp,
            # "RADIUS": 2,
            # "STATS": 1,     # MIN (erosion)
            # "OUTPUT": path_raster_slopeopen
        # }
    # )
    # os.remove(tmp)

    processing.run("grass:r.neighbors",
        {
            "input": path_raster_slopemask,
            "method":  "minimum",
            "size": 5,                # window size in cells (odd number)
            "output": tmp,
            "GRASS_REGION_PARAMETER": None,
            "GRASS_REGION_CELLSIZE_PARAMETER": 0
        }
    )
    processing.run("grass:r.neighbors",
        {
            "input": tmp,
            "method":  "maximum",
            "size": 5,                # window size in cells (odd number)
            "output": path_raster_slopeopen,
            "GRASS_REGION_PARAMETER": None,
            "GRASS_REGION_CELLSIZE_PARAMETER": 0
        }
    )
    os.remove(tmp)




    # 3) Polygonise

    result = processing.run("gdal:polygonize",
        {
            "INPUT": path_raster_slopeopen,
            "BAND": 1,
            "FIELD": "DN",
            "EIGHT_CONNECTEDNESS": False,
            "EXTRA": "",
            "OUTPUT": path_vector_slopepoly 
        }
    )
 
    # 4) Extracy steep polys

    #formula = f"\"DN\" = 1 AND $area > {steepcull}"
    formula = f"\"DN\" = 1 AND $area > 50"
    result = processing.run("native:extractbyexpression",
        {
            "INPUT": path_vector_slopepoly,
            "EXPRESSION": formula,
            "OUTPUT": path_vector_steeppoly_holes
        }
    )

    # 5) Delete holes

    result = processing.run("native:deleteholes",
        {
            "INPUT": path_vector_steeppoly_holes,
            "MIN_AREA": 50,
            "OUTPUT": path_vector_steeppoly_noholes
        }
    )

    # 6) out to in buffering 
    
    result = processing.run("native:buffer",
        {
            "INPUT": path_vector_steeppoly_noholes,
            "DISTANCE": 2,
            "SEGMENTS": 5,
            "END_CAP_STYLE": 0,
            "JOIN_STYLE": 0,
            "MITER_LIMIT": 2,
            "DISSOLVE": False,
            "OUTPUT": path_vector_bufferout
        }
    )
    result = processing.run("native:buffer",
        {
            "INPUT": path_vector_bufferout,
            "DISTANCE": -2,
            "SEGMENTS": 5,
            "END_CAP_STYLE": 0,
            "JOIN_STYLE": 0,
            "MITER_LIMIT": 2,
            "DISSOLVE": False,
            "OUTPUT": path_vector_steeppoly
        }
    )

    # 7) get shallow poly by difference

    result = processing.run("native:difference",
        {
            "INPUT": clipmask,                # A: QgsVectorLayer or path
            "OVERLAY": path_vector_steeppoly,            # B: QgsVectorLayer or path
            "INPUT_FIELDS": [],                  # [] = keep all A fields (QGIS ≥3.22)
            "OVERLAY_FIELDS": [],                # [] = keep all B fields where handy
            "INPUT_FIELDS_PREFIX": "",           # optional prefix for A fields
            "OVERLAY_FIELDS_PREFIX": "B_",       # optional prefix for B fields
            "GRID_SIZE": 0.0,                    # 0 = no snap; set e.g. 0.001 to snap/clean
            "OUTPUT": path_vector_shallowpoly    # or "TEMPORARY_OUTPUT"
        }
    )


       
    
    if debug:
        from .out_helpers import add_raster, add_vector

        _ = add_raster(path_raster_slopemask, "2-SlopeMask - SlopeMask")
        _ = add_raster(path_raster_slopeopen, "2-SlopeMask - SlopeOpen")
        _ = add_vector(path_vector_slopepoly, "2-SlopeMask - SlopePoly")
        _ = add_vector(path_vector_steeppoly_holes, "2-SlopeMask - SteepPoly With Holes")
        _ = add_vector(path_vector_steeppoly_noholes, "2-SlopeMask - SteepPoly No Holes")
        _ = add_vector(path_vector_steeppoly, "2-SlopeMask - SteepPoly OUT")
        _ = add_vector(path_vector_shallowpoly, "2-SlopeMask - ShallowPoly OUT")


    return path_vector_steeppoly, path_vector_shallowpoly