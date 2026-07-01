# acm4/feat_merge/py

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
    point_over0, 
    break_over0, 
    mask_over0, 
    point_over1, 
    break_over1, 
    mask_over1, 
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
    
    from .out_helpers import _temp_vector
    
    path_vector_points_ground_product = _temp_vector("acm4_delaunay_ground_points")
    path_vector_breaks_ground_product = _temp_vector("acm4_delaunay_ground_breaks")

    path_vector_points_slope_merged = _temp_vector("acm4_points_slope_merged")
    path_vector_poly_over0_buffer = _temp_vector("acm4_poly_over0_buffer")
    path_vector_poly_over1_buffer = _temp_vector("acm4_poly_over1_buffer")
    path_vector_points_slope_culled = _temp_vector("acm4_points_slope_culled")
    path_vector_points_over0_merged = _temp_vector("acm4_points_over0_merged")
    path_vector_points_over1_merged = _temp_vector("acm4_points_over1_merged")
    path_vector_poly_corr_buffer = _temp_vector("acm4_poly_corr_buffer")
    path_vector_points_over0_culled = _temp_vector("acm4_points_over0_culled")
    path_vector_points_over1_culled = _temp_vector("acm4_points_over1_culled")
    path_vector_points_corr_merged = _temp_vector("acm4_points_corr_merged")
    path_vector_poly_extent_buffer = _temp_vector("acm4_poly_extent_buffer")
    path_vector_extents_to_line = _temp_vector("acm4_extents_to_line")
    path_vector_points_extent_culled = _temp_vector("acm4_points_extent_culled")
    path_vector_breaks_extent_single = _temp_vector("acm4_breaks_extent_single")
    path_vector_breaks_extent_explode = _temp_vector("acm4_breaks_extent_explode")
    path_vector_points_extent_perimeter = _temp_vector("acm4_points_extent_perimeter")
    path_vector_points_extent_perimeter_Z = _temp_vector("acm4_points_extent_perimeter_Z")


    
    # merge steep and shallow points
    
    result = processing.run("native:mergevectorlayers",
        {
            "LAYERS": [point_steep, point_shallow],
            "OUTPUT": path_vector_points_slope_merged
        }
    )
    
    # cutout override buffered mask_over0
    
    result = processing.run("native:buffer",
        {
            "INPUT": mask_over0,
            "DISTANCE": 0.5,
            "SEGMENTS": 5,
            "END_CAP_STYLE": 0,
            "JOIN_STYLE": 0,
            "MITER_LIMIT": 2,
            "DISSOLVE": False,
            "OUTPUT": path_vector_poly_over0_buffer
        }
    )
    result = processing.run("native:difference",
        {
            "INPUT": path_vector_points_slope_merged,
            "OVERLAY": path_vector_poly_over0_buffer,
            "INPUT_FIELDS": [],
            "OVERLAY_FIELDS": [],
            "INPUT_FIELDS_PREFIX": "",
            "OVERLAY_FIELDS_PREFIX": "B_",
            "GRID_SIZE": 0.001,
            "OUTPUT": path_vector_points_slope_culled
        }
    )
    
    # merge slope and override 0 points

    result = processing.run("native:mergevectorlayers",
        {
            "LAYERS": [path_vector_points_slope_culled, point_over0],
            "OUTPUT": path_vector_points_over0_merged
        }
    )

    # cutout override buffered mask_over1
    
    result = processing.run("native:buffer",
        {
            "INPUT": mask_over1,
            "DISTANCE": 0.5,
            "SEGMENTS": 5,
            "END_CAP_STYLE": 0,
            "JOIN_STYLE": 0,
            "MITER_LIMIT": 2,
            "DISSOLVE": False,
            "OUTPUT": path_vector_poly_over1_buffer
        }
    )
    result = processing.run("native:difference",
        {
            "INPUT": path_vector_points_over0_merged,
            "OVERLAY": path_vector_poly_over1_buffer,
            "INPUT_FIELDS": [],
            "OVERLAY_FIELDS": [],
            "INPUT_FIELDS_PREFIX": "",
            "OVERLAY_FIELDS_PREFIX": "B_",
            "GRID_SIZE": 0.001,
            "OUTPUT": path_vector_points_over0_culled
        }
    )
    
    # merge override 0 and override 1points

    result = processing.run("native:mergevectorlayers",
        {
            "LAYERS": [path_vector_points_over0_culled, point_over1],
            "OUTPUT": path_vector_points_over1_merged
        }
    )


    
    # cutout corridor buffered mask_corr
    
    result = processing.run("native:buffer",
        {
            "INPUT": mask_corr,
            "DISTANCE": 0.5,
            "SEGMENTS": 5,
            "END_CAP_STYLE": 0,
            "JOIN_STYLE": 0,
            "MITER_LIMIT": 2,
            "DISSOLVE": False,
            "OUTPUT": path_vector_poly_corr_buffer
        }
    )
    result = processing.run("native:difference",
        {
            "INPUT": path_vector_points_over1_merged,
            "OVERLAY": path_vector_poly_corr_buffer,
            "INPUT_FIELDS": [],
            "OVERLAY_FIELDS": [],
            "INPUT_FIELDS_PREFIX": "",
            "OVERLAY_FIELDS_PREFIX": "B_",
            "GRID_SIZE": 0.001,
            "OUTPUT": path_vector_points_over_culled
        }
    )
 
    # merge slope/override and corridor points

    result = processing.run("native:mergevectorlayers",
        {
            "LAYERS": [path_vector_points_over1_culled, point_corr],
            "OUTPUT": path_vector_points_corr_merged
        }
    )
 
    # buffer (shrink) extents and trim points
    
    result = processing.run("native:buffer",
        {
            "INPUT": extents,
            "DISTANCE": -1.0,
            "SEGMENTS": 5,
            "END_CAP_STYLE": 0,
            "JOIN_STYLE": 0,
            "MITER_LIMIT": 2,
            "DISSOLVE": False,
            "OUTPUT": path_vector_poly_extent_buffer
        }
    )
    result = processing.run("native:intersection",
        {
            "INPUT": path_vector_points_corr_merged,
            "OVERLAY": path_vector_poly_extent_buffer,
            "INPUT_FIELDS": [],              
            "OVERLAY_FIELDS": [], 
            "GRID_SIZE": 0.001,    
            "OUTPUT": path_vector_points_extent_culled   
        }
    )

    # create outline points and breaks
    
    result = processing.run("native:polygonstolines",
        {
            "INPUT": extents,
            "OUTPUT": path_vector_extents_to_line
        }
    )
    
    result = processing.run("native:densifygeometriesgivenaninterval",
        {
            "INPUT": path_vector_extents_to_line,
            "INTERVAL": 5.0,
            "OUTPUT": path_vector_breaks_extent_single
        }
    )

    result = processing.run("native:extractvertices",
        {
            "INPUT": path_vector_breaks_extent_single,
            "OUTPUT": path_vector_points_extent_perimeter
        }
    )

    result = processing.run("native:explodelines",
        {
            "INPUT": path_vector_breaks_extent_single,
            "OUTPUT": path_vector_breaks_extent_explode
        }
    )

    result = processing.run("native:setzfromraster",
        {
            "INPUT": path_vector_points_extent_perimeter,
            "RASTER": dtm,
            "BAND": 1,
            "OUTPUT": path_vector_points_extent_perimeter_Z
        }
    )

    # merge main and extent points

    result = processing.run("native:mergevectorlayers",
        {
            "LAYERS": [path_vector_points_extent_culled, path_vector_points_extent_perimeter_Z],
            "OUTPUT": path_vector_points_ground_product
        }
    )
 
    # merge override and corridor breaklines

    result = processing.run("native:mergevectorlayers",
        {
            "LAYERS": [break_over0, break_over1, break_corr, path_vector_breaks_extent_explode],
            "OUTPUT": path_vector_breaks_ground_product
        }
    )


    if debug:
        from .out_helpers import add_vector

        _ = add_vector(path_vector_points_slope_merged, "7-FeatureMerge - Slope Points Merged")
        _ = add_vector(path_vector_poly_over_buffer, "7-FeatureMerge - Override Mask")
        _ = add_vector(path_vector_points_slope_culled, "7-FeatureMerge - Slope Points With Override Cutout")
        _ = add_vector(path_vector_points_over_merged, "7-FeatureMerge - Override Points Merged")
        _ = add_vector(path_vector_poly_corr_buffer, "7-FeatureMerge - Corridor Mask")
        _ = add_vector(path_vector_points_over_culled, "7-FeatureMerge - Slope/Override Points With Corridor Cutout")
        _ = add_vector(path_vector_points_corr_merged, "7-FeatureMerge - Corridor Points Merged")
        _ = add_vector(path_vector_poly_extent_buffer, "7-FeatureMerge - Extent Mask")
        _ = add_vector(path_vector_points_extent_culled, "7-FeatureMerge - Points Trimmed To Extents")
        _ = add_vector(path_vector_points_extent_perimeter_Z, "7-FeatureMerge - Perimeter Points")

        _ = add_vector(path_vector_points_ground_product, "7-FeatureMerge - Corridor Points Merged (final product)")
        _ = add_vector(path_vector_breaks_ground_product, "7-FeatureMerge - Breaklines Merged (final product)")


    return path_vector_points_ground_product, path_vector_breaks_ground_product

    



    
    