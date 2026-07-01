# acm4/boundaries.py

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

def do(network_grounded, network_raised, debug = False ):
    """
        by
    """
    from .out_helpers import _temp_vector, add_vector
    
    boundaries_out = _temp_vector("boundaries_out")

    # NETWORK GROUNDED
    #
    # replace 'SLOPE' with 'NORM'
    formula = """
    CASE
        WHEN "type" = 'SLOPE' THEN 'NORM'
        ELSE "type"
    END
    """

    result = processing.run("native:fieldcalculator",
        {
            "INPUT": network_grounded,
            "FIELD_NAME": "type",
            "FIELD_TYPE": 2,                 # String
            "FIELD_LENGTH": 30,
            "FIELD_PRECISION": 0,
            "NEW_FIELD": False,              # overwrite existing 'type'
            "FORMULA": formula,
            "OUTPUT": "TEMPORARY_OUTPUT"
        }
    )
    normed = result["OUTPUT"]
    
    # dissolve on "type"
    result = processing.run("native:dissolve",
        {
            "INPUT": normed,
            "FIELD": ["type"],
            "SEPARATE_DISJOINT": True,
            "OUTPUT": "TEMPORARY_OUTPUT"
        }
    )
    grounded_clumps = result["OUTPUT"]
   
    # polygons to lines
    result = processing.run("native:polygonstolines",
        {
            "INPUT": grounded_clumps,
            "OUTPUT": "TEMPORARY_OUTPUT"
        }
    )
    grounded_boundaries = result["OUTPUT"]

    # NETWORK RAISED
    #
    # dissolve on "type"
    result = processing.run("native:dissolve",
        {
            "INPUT": network_raised,
            "FIELD": ["type"],
            "SEPARATE_DISJOINT": True,
            "OUTPUT": "TEMPORARY_OUTPUT"
        }
    )
    raised_clumps = result["OUTPUT"]
   
    # polygons to lines
    result = processing.run("native:polygonstolines",
        {
            "INPUT": raised_clumps,
            "OUTPUT": "TEMPORARY_OUTPUT"
        }
    )
    raised_boundaries = result["OUTPUT"]

    # merge boundary sets
    result = processing.run("native:mergevectorlayers",
        {
            "LAYERS": [grounded_boundaries, raised_boundaries],
            "OUTPUT": boundaries_out
        }
    )




    return boundaries_out

