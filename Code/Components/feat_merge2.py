# acm4/feat_merge2/py

from qgis.core import (
    QgsVectorLayer,
    QgsRasterLayer,
    QgsPointXY,
    QgsGeometry,
    QgsRectangle,
    QgsFeature,
    QgsSpatialIndex,
    QgsCoordinateReferenceSystem,
    QgsProject
)

import processing

def do(
    point_steep, 
    point_shallow, 
    point_over_0, 
    break_over_0, 
    mask_over_0, 
    point_over_1, 
    break_over_1, 
    mask_over_1, 
    point_corr, 
    break_corr, 
    mask_corr, 
    extents, 
    dtm, 
    debug
    ):
    """
        combine gridpoints and breaklines (basic, corridor, override)
        use (buffered) polygon masks to cutout lower-order points prior
        to merging of higher-order points:
        place slope points --> cut out for override points
        place override points --> cut out for corridor points
        place corridor points
        breaklines added as is.
        returns 3d points and 2d breaklines for delaunay triangulation
    """
    
    from .out_helpers import _temp_vector, add_vector, as_path, safe_save_vector
    
    # out0 = _temp_vector("out0")
    # out1 = _temp_vector("out1")
    # out2 = _temp_vector("out2")
    # out3 = _temp_vector("out3")
    
    # out = [ out0, out1, out2, out3 ]
 
    out_pnt = [ _temp_vector("out_pnt_" + str(n)) for n in [0,1,2,3] ]
    out_brk = [ _temp_vector("out_brk_" + str(n)) for n in [0,1,2,3] ]
 
    # ------------------------
    # process slope points
    # ------------------------

    # shrink extents (for slope point cull)
    extents_pgon_shrink = processing.run("native:buffer",
        {
            "INPUT": extents,
            "DISTANCE": -1.0,
            "SEGMENTS": 5,
            "END_CAP_STYLE": 0,
            "JOIN_STYLE": 0,
            "MITER_LIMIT": 2,
            "DISSOLVE": False,
            "OUTPUT": "TEMPORARY_OUTPUT"
        }
    )["OUTPUT"]

    # merge steep and shallow points
    slope_pnts_merged = processing.run("native:mergevectorlayers",
        {
            "LAYERS": [point_steep, point_shallow],
            "OUTPUT": "TEMPORARY_OUTPUT"
        }
    )["OUTPUT"]

    # clip slope points by shrink extents
    SLOPE_PNTS_Z = processing.run("native:intersection",
        {                                                           # =====>>>>>
            "INPUT": slope_pnts_merged,
            "OVERLAY": extents_pgon_shrink,
            "INPUT_FIELDS": [],              
            "OVERLAY_FIELDS": [], 
            "GRID_SIZE": 0.001,    
            "OUTPUT": "TEMPORARY_OUTPUT"
        }
    )["OUTPUT"]                                     
    
    # ------------------------
    # process extents geometry
    # ------------------------
    
    # polygon to linestring
    extents_line_boundary = processing.run("native:polygonstolines",
        {
            "INPUT": extents,
            "OUTPUT": "TEMPORARY_OUTPUT"
        }
    )["OUTPUT"]
    
    # linestring into divisions
    extents_line_divisions = processing.run("native:densifygeometriesgivenaninterval",
        {
            "INPUT": extents_line_boundary,
            "INTERVAL": 5.0,
            "OUTPUT": "TEMPORARY_OUTPUT"
        }
    )["OUTPUT"]
    
    # divisions into vertices
    extents_pnts_xy = processing.run("native:extractvertices",
        {
            "INPUT": extents_line_divisions,
            "OUTPUT": "TEMPORARY_OUTPUT"
        }
    )["OUTPUT"]


    # promote points to raster
    EXTENTS_PNTS_Z = processing.run("native:setzfromraster",
        {                                                           # =====>>>>>
            "INPUT": extents_pnts_xy,
            "RASTER": dtm,
            "BAND": 1,
            "OUTPUT": "TEMPORARY_OUTPUT"
        }
    )["OUTPUT"]
    

    # divisions into lines
    EXTENTS_LINES_EXPLODE = processing.run("native:explodelines",
        {                                                           # =====>>>>>
            "INPUT": extents_line_divisions,
            "OUTPUT": out_brk[0]
        }
    )    
 
 
    # collate stage 1 results

    STAGE_1_BREAKS = processing.run("native:mergevectorlayers",
        {                                                           # =====>>>>>
            "LAYERS": [EXTENTS_PNTS_Z, SLOPE_PNTS_Z],
            "OUTPUT": out_pnt[0]
        }
    )


    # ------------------------
    # gdor / corr loop
    # ------------------------
    
    # init
    
    mask    = [ mask_over_0,    mask_over_1,    mask_corr   ]
    point   = [ point_over_0,   point_over_1,   point_corr  ]
    lines   = [ break_over_0,  break_over_1,   break_corr   ]
    growth  = [ 0.5, 0.5, 1.0 ]

    # loop
    for n in [0,1,2]:
        
        # mask
        grow_mask = processing.run("native:buffer",
            {
                "INPUT": mask[n],
                "DISTANCE": growth[n],
                "SEGMENTS": 5,
                "END_CAP_STYLE": 0,
                "JOIN_STYLE": 0,
                "MITER_LIMIT": 2,
                "DISSOLVE": False,
                "OUTPUT": "TEMPORARY_OUTPUT"
            }
        )["OUTPUT"]
        
       # clear points
        pnt_hole_punched = processing.run("native:difference",
            {
                "INPUT": out_pnt[n],
                "OVERLAY": grow_mask,
                "INPUT_FIELDS": [],
                "OVERLAY_FIELDS": [],
                "INPUT_FIELDS_PREFIX": "",
                "OVERLAY_FIELDS_PREFIX": "_",
                "GRID_SIZE": 0.001,
                "OUTPUT": "TEMPORARY_OUTPUT"
            }
        )["OUTPUT"]
        
        # merge old new points
        combined = processing.run("native:mergevectorlayers",
            {
                "LAYERS": [pnt_hole_punched, point[n]],
                "OUTPUT": out_pnt[n+1]
            }
        )
        
       # clear breaks
        brk_hole_punched = processing.run("native:extractbylocation",
            {
                "INPUT": out_brk[n],
                "PREDICATE": [2],        # 2 = disjoint
                "INTERSECT": grow_mask,
                "OUTPUT": "TEMPORARY_OUTPUT"
            }
        )["OUTPUT"]
        
        # merge old new breaks
        combined = processing.run("native:mergevectorlayers",
            {
                "LAYERS": [brk_hole_punched, lines[n]],
                "OUTPUT": out_brk[n+1]
            }
        )
 


    if debug:
        from .out_helpers import add_vector
        
        a = 1
        

    return out_pnt[3], out_brk[3]



    
    