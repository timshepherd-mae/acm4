# acm4/form_triang3.py

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

def do(del_tri, del_tri_raised, mask_gdor_0, mask_gdor_1, mask_corr, slope_thresh, debug = False ):
    """
        ft2
    """
    from .out_helpers import _temp_vector, add_vector
    
    tri_grounded_out = _temp_vector("tri_grounded_out")
    tri_raised_out = _temp_vector("tri_raised_out")

    # add 'NORM' to all grounded triangles
    result = processing.run("native:fieldcalculator",
        {
            "INPUT": del_tri,
            "FIELD_NAME": "type",
            "FIELD_TYPE": 2,                 # String
            "FIELD_LENGTH": 30,
            "FIELD_PRECISION": 0,
            "NEW_FIELD": False,              # overwrite existing 'type'
            "FORMULA": "'NORM'",
            "OUTPUT": "TEMPORARY_OUTPUT"
        }
    )
    normed = result["OUTPUT"]
    
    # # apply slope values to triangles
    # formula = """
    # with_variable('p1', point_n($geometry, 1),
    # with_variable('p2', point_n($geometry, 2),
    # with_variable('p3', point_n($geometry, 3),
    # with_variable('v1x', x(@p2) - x(@p1),
    # with_variable('v1y', y(@p2) - y(@p1),
    # with_variable('v1z', z(@p2) - z(@p1),
    # with_variable('v2x', x(@p3) - x(@p1),
    # with_variable('v2y', y(@p3) - y(@p1),
    # with_variable('v2z', z(@p3) - z(@p1),
    # with_variable('nx', @v1y*@v2z - @v1z*@v2y,
    # with_variable('ny', @v1z*@v2x - @v1x*@v2z,
    # with_variable('nz', @v1x*@v2y - @v1y*@v2x,
    # CASE
      # WHEN @nx = 0 AND @ny = 0 AND @nz = 0 THEN NULL
      # WHEN abs(@nz) = 0 THEN 90
      # ELSE degrees( atan2( sqrt(@nx*@nx + @ny*@ny), abs(@nz) ) )
    # END
    # ))))))))))))
    # """

    # result = processing.run("native:fieldcalculator",
        # {
            # "INPUT": normed,
            # "FIELD_NAME": "slope",
            # "FIELD_TYPE": 2,                 # String
            # "FIELD_LENGTH": 30,
            # "FIELD_PRECISION": 0,
            # "NEW_FIELD": False,              # overwrite existing 'type'
            # "FORMULA": formula,
            # "OUTPUT": "TEMPORARY_OUTPUT"
        # }
    # )
    # slope_added = result["OUTPUT"]

    # # apply 'type = slope' if type == norm
    # # do after all other type writes
    # formula = f"""
    # CASE
        # WHEN "slope" > {slope_thresh} THEN 'SLOPE'
        # ELSE "type"
    # END
    # """

    # result = processing.run("native:fieldcalculator",
        # {
            # "INPUT": slope_added,
            # "FIELD_NAME": "type",
            # "FIELD_TYPE": 2,                 # String
            # "FIELD_LENGTH": 30,
            # "FIELD_PRECISION": 0,
            # "NEW_FIELD": False,              # overwrite existing 'type'
            # "FORMULA": formula,
            # "OUTPUT": "TEMPORARY_OUTPUT"
        # }
    # )
    # sloped = result["OUTPUT"]
    

    # GDOR_0
    #
    # buffer the mask
    result = processing.run("native:buffer",
        {
            "INPUT": mask_gdor_0,
            "DISTANCE": -0.25,
            "SEGMENTS": 5,
            "END_CAP_STYLE": 0,
            "JOIN_STYLE": 0,
            "MITER_LIMIT": 2,
            "DISSOLVE": False,
            "OUTPUT": "TEMPORARY_OUTPUT"
        }
    )
    buffered = result["OUTPUT"]
    
    # join the mask field 'type' to triangles
    result = processing.run("native:joinattributesbylocation",
        {
            "INPUT": normed,
            # "INPUT": sloped,
            "JOIN": buffered ,
            "PREDICATE": [0],            # 0 = intersects
            "JOIN_FIELDS": ["type"],     # bring only 'type' across
            "METHOD": 1,                 # 1 = first match one-on-one
            "DISCARD_NONMATCHING": False,
            "PREFIX": "mask_",           # joined field will be 'mask_type'
            "OUTPUT": "TEMPORARY_OUTPUT"
        }
    )
    joined = result["OUTPUT"]
    
    # update field 'type' for triangles
    result = processing.run("native:fieldcalculator",
        {
            "INPUT": joined,
            "FIELD_NAME": "type",
            "FIELD_TYPE": 2,                 # String
            "FIELD_LENGTH": 30,
            "FIELD_PRECISION": 0,
            "NEW_FIELD": False,              # overwrite existing 'type'
            "FORMULA": "coalesce(\"mask_type\", \"type\")",
            "OUTPUT": "TEMPORARY_OUTPUT"
        }
    )
    updated = result["OUTPUT"]
    
    # delete mask column
    result = processing.run("native:deletecolumn",
        {
            "INPUT": updated,               # QgsVectorLayer or path
            "COLUMN": ["mask_type"],        # list of field names to delete
            "OUTPUT": "TEMPORARY_OUTPUT"    # or your _temp_vector() path
        }
    )
    gdor_0_final = result["OUTPUT"]    


    # GDOR_1
    #
    # buffer the mask
    result = processing.run("native:buffer",
        {
            "INPUT": mask_gdor_1,
            "DISTANCE": -0.25,
            "SEGMENTS": 5,
            "END_CAP_STYLE": 0,
            "JOIN_STYLE": 0,
            "MITER_LIMIT": 2,
            "DISSOLVE": False,
            "OUTPUT": "TEMPORARY_OUTPUT"
        }
    )
    buffered = result["OUTPUT"]
    
    # join the mask field 'type' to triangles
    result = processing.run("native:joinattributesbylocation",
        {
            "INPUT": gdor_0_final,
            "JOIN": buffered ,
            "PREDICATE": [0],            # 0 = intersects
            "JOIN_FIELDS": ["type"],     # bring only 'type' across
            "METHOD": 1,                 # 1 = first match one-on-one
            "DISCARD_NONMATCHING": False,
            "PREFIX": "mask_",           # joined field will be 'mask_type'
            "OUTPUT": "TEMPORARY_OUTPUT"
        }
    )
    joined = result["OUTPUT"]
    
    # update field 'type' for triangles
    result = processing.run("native:fieldcalculator",
        {
            "INPUT": joined,
            "FIELD_NAME": "type",
            "FIELD_TYPE": 2,                 # String
            "FIELD_LENGTH": 30,
            "FIELD_PRECISION": 0,
            "NEW_FIELD": False,              # overwrite existing 'type'
            "FORMULA": "coalesce(\"mask_type\", \"type\")",
            "OUTPUT": "TEMPORARY_OUTPUT"
        }
    )
    updated = result["OUTPUT"]
    
    # delete mask column
    result = processing.run("native:deletecolumn",
        {
            "INPUT": updated,               # QgsVectorLayer or path
            "COLUMN": ["mask_type"],        # list of field names to delete
            "OUTPUT": "TEMPORARY_OUTPUT"    # or your _temp_vector() path
        }
    )
    gdor_1_final = result["OUTPUT"]    

    
    # CORR
    #
    # buffer the mask
    result = processing.run("native:buffer",
        {
            "INPUT": mask_corr,
            "DISTANCE": -0.25,
            "SEGMENTS": 5,
            "END_CAP_STYLE": 0,
            "JOIN_STYLE": 0,
            "MITER_LIMIT": 2,
            "DISSOLVE": False,
            "OUTPUT": "TEMPORARY_OUTPUT"
        }
    )
    buffered = result["OUTPUT"]
    
    # join the mask field 'type' to triangles
    result = processing.run("native:joinattributesbylocation",
        {
            "INPUT": gdor_1_final,
            "JOIN": buffered ,
            "PREDICATE": [0],            # 0 = intersects
            "JOIN_FIELDS": ["type"],     # bring only 'type' across
            "METHOD": 1,                 # 1 = first match one-on-one
            "DISCARD_NONMATCHING": False,
            "PREFIX": "mask_",           # joined field will be 'mask_type'
            "OUTPUT": "TEMPORARY_OUTPUT"
        }
    )
    joined = result["OUTPUT"]
    
    # update field 'type' for triangles
    result = processing.run("native:fieldcalculator",
        {
            "INPUT": joined,
            "FIELD_NAME": "type",
            "FIELD_TYPE": 2,                 # String
            "FIELD_LENGTH": 30,
            "FIELD_PRECISION": 0,
            "NEW_FIELD": False,              # overwrite existing 'type'
            "FORMULA": "coalesce(\"mask_type\", \"type\")",
            "OUTPUT": "TEMPORARY_OUTPUT"
        }
    )
    updated = result["OUTPUT"]
    
    # delete mask column
    result = processing.run("native:deletecolumn",
        {
            "INPUT": updated,               # QgsVectorLayer or path
            "COLUMN": ["mask_type"],        # list of field names to delete
            "OUTPUT": "TEMPORARY_OUTPUT"    # tri_grounded_out 
        }
    )
    gdor_1_final = result["OUTPUT"]    

    
    # SLOPES
    #
    # calculate triangle slopes and apply SLOPE to NORM

    # apply slope values to triangles
    formula = """
    with_variable('p1', point_n($geometry, 1),
    with_variable('p2', point_n($geometry, 2),
    with_variable('p3', point_n($geometry, 3),
    with_variable('v1x', x(@p2) - x(@p1),
    with_variable('v1y', y(@p2) - y(@p1),
    with_variable('v1z', z(@p2) - z(@p1),
    with_variable('v2x', x(@p3) - x(@p1),
    with_variable('v2y', y(@p3) - y(@p1),
    with_variable('v2z', z(@p3) - z(@p1),
    with_variable('nx', @v1y*@v2z - @v1z*@v2y,
    with_variable('ny', @v1z*@v2x - @v1x*@v2z,
    with_variable('nz', @v1x*@v2y - @v1y*@v2x,
    CASE
      WHEN @nx = 0 AND @ny = 0 AND @nz = 0 THEN NULL
      WHEN abs(@nz) = 0 THEN 90
      ELSE degrees( atan2( sqrt(@nx*@nx + @ny*@ny), abs(@nz) ) )
    END
    ))))))))))))
    """

    result = processing.run("native:fieldcalculator",
        {
            "INPUT": gdor_1_final,
            "FIELD_NAME": "slope",
            "FIELD_TYPE": 2,                 # String
            "FIELD_LENGTH": 30,
            "FIELD_PRECISION": 0,
            "NEW_FIELD": False,              # overwrite existing 'type'
            "FORMULA": formula,
            "OUTPUT": "TEMPORARY_OUTPUT"
        }
    )
    slope_added = result["OUTPUT"]

    # apply 'type = slope' if type == norm
    formula = f"""
    CASE
        WHEN "slope" > {slope_thresh} AND "type" = 'NORM' THEN 'SLOPE'
        ELSE "type"
    END
    """

    result = processing.run("native:fieldcalculator",
        {
            "INPUT": slope_added,
            "FIELD_NAME": "type",
            "FIELD_TYPE": 2,                 # String
            "FIELD_LENGTH": 30,
            "FIELD_PRECISION": 0,
            "NEW_FIELD": False,              # overwrite existing 'type'
            "FORMULA": formula,
            "OUTPUT": tri_grounded_out      # "TEMPORARY_OUTPUT"
        }
    )
    # sloped = result["OUTPUT"]



    # OVERPASS
    #
    # add 'OVER' to all raised triangles
    result = processing.run("native:fieldcalculator",
        {
            "INPUT": del_tri_raised,
            "FIELD_NAME": "type",
            "FIELD_TYPE": 2,                 # String
            "FIELD_LENGTH": 30,
            "FIELD_PRECISION": 0,
            "NEW_FIELD": False,              # overwrite existing 'type'
            "FORMULA": "'OVER'",
            "OUTPUT": tri_raised_out
        }
    )
    # normed = result["OUTPUT"]


    return tri_grounded_out, tri_raised_out

