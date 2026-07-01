# acm4/delaunay.py

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

def do_one(points, breaks, mask, debug):
    """
        build basic unconstrained delaunay, fix geom,
        add spatial index, extract by (shink) mask
        returns a single set of triangles
    """
    
    from .out_helpers import _temp_vector
    from .delaunay_helper import build_triangulation

    
    
    path_vector_poly_delaunay = _temp_vector("acm4_poly_delaunay")
    path_vector_poly_delaunay_fixed = _temp_vector("acm4_poly_delaunay_fixed")
    path_vector_poly_extents_shrink = _temp_vector("acm4_poly_extents_shrink")
    path_vector_poly_delaunay_clipped = _temp_vector("acm4_poly_delaunay_clipped")
    path_vector_poly_delaunay_typed = _temp_vector("acm4_poly_delaunay_typed")

    
    # build delaunay
    
    path_vector_poly_delaunay = build_triangulation(points, breaks, path_vector_poly_delaunay)
    
    # fix geometries
    
    result = processing.run("native:fixgeometries",
        {
            "INPUT": path_vector_poly_delaunay,
            "METHOD": 1,
            "OUTPUT": path_vector_poly_delaunay_fixed
        }
    )

    # spatial index

    result = processing.run("native:createspatialindex",
        {
            "INPUT": path_vector_poly_delaunay_fixed
        }
    )

    # buffer (shrink) mask

    result = processing.run("native:buffer",
        {
            "INPUT": mask,
            "DISTANCE": -0.1,          # buffer distance in layer units
            "SEGMENTS": 5,            # segmentation for round joins
            "END_CAP_STYLE": 2,       # 0 = round, 1 = flat, 2 = square
            "JOIN_STYLE": 1,          # 0 = round, 1 = mitre, 2 = bevel
            "MITER_LIMIT": 2,
            "DISSOLVE": False,
            "OUTPUT": path_vector_poly_extents_shrink
        }
    )

    # extract clipped delaunay

    result = processing.run("native:extractbylocation",
        {
            "INPUT": path_vector_poly_delaunay_fixed,
            "PREDICATE": [0],
            "INTERSECT": path_vector_poly_extents_shrink,
            "OUTPUT": path_vector_poly_delaunay_clipped
        }
    )
    
    # add 'type' field to all remaining triangles

    result = processing.run("native:addfieldtoattributestable",
        {
            "INPUT": path_vector_poly_delaunay_clipped,
            "FIELD_NAME": "type",
            "FIELD_TYPE": 2,
            "FIELD_LENGTH": 10,
            "FIELD_PRECISION": 3,
            "OUTPUT": path_vector_poly_delaunay_typed
        }
    ) 

    

    if debug:
        from .out_helpers import add_vector

        _ = add_vector(path_vector_poly_delaunay, "8-Delaunay - Raw Triangles")
        _ = add_vector(path_vector_poly_delaunay_fixed, "8-Delaunay - Fixed Triangles")
        _ = add_vector(path_vector_poly_extents_shrink, "8-Delaunay - Shrink Mask")
        _ = add_vector(path_vector_poly_delaunay_clipped, "8-Delaunay - Clipped Triangles")
        _ = add_vector(path_vector_poly_delaunay_typed, "8-Delaunay - Typed Triangles")


    return path_vector_poly_delaunay_typed

    
def do_two(points, breaks, mask, debug):
    """
        build basic unconstrained delaunay, fix geom,
        add spatial index, extract by (shink) mask
        returns a single set of triangles
    """
    
    from .out_helpers import _temp_vector
    from .delaunay_helper import build_triangulation

    
    
    path_vector_poly_delaunay2 = _temp_vector("acm4_poly_delaunay2")
    path_vector_poly_delaunay_fixed2 = _temp_vector("acm4_poly_delaunay_fixed2")
    path_vector_poly_extents_shrink2 = _temp_vector("acm4_poly_extents_shrink2")
    path_vector_poly_delaunay_clipped2 = _temp_vector("acm4_poly_delaunay_clipped2")
    path_vector_poly_delaunay_typed2 = _temp_vector("acm4_poly_delaunay_typed2")

    
    # build delaunay
    
    path_vector_poly_delaunay2 = build_triangulation(points, breaks, path_vector_poly_delaunay2)
    
    # fix geometries
    
    result = processing.run("native:fixgeometries",
        {
            "INPUT": path_vector_poly_delaunay2,
            "METHOD": 1,
            "OUTPUT": path_vector_poly_delaunay_fixed2
        }
    )

    # spatial index

    result = processing.run("native:createspatialindex",
        {
            "INPUT": path_vector_poly_delaunay_fixed2
        }
    )

    # buffer (shrink) mask

    result = processing.run("native:buffer",
        {
            "INPUT": mask,
            "DISTANCE": -0.1,          # buffer distance in layer units
            "SEGMENTS": 5,            # segmentation for round joins
            "END_CAP_STYLE": 2,       # 0 = round, 1 = flat, 2 = square
            "JOIN_STYLE": 1,          # 0 = round, 1 = mitre, 2 = bevel
            "MITER_LIMIT": 2,
            "DISSOLVE": False,
            "OUTPUT": path_vector_poly_extents_shrink2
        }
    )

    # extract clipped delaunay

    result = processing.run("native:extractbylocation",
        {
            "INPUT": path_vector_poly_delaunay_fixed2,
            "PREDICATE": [0],
            "INTERSECT": path_vector_poly_extents_shrink2,
            "OUTPUT": path_vector_poly_delaunay_clipped2
        }
    )
    
    # add 'type' field to all remaining triangles

    result = processing.run("native:addfieldtoattributestable",
        {
            "INPUT": path_vector_poly_delaunay_clipped2,
            "FIELD_NAME": "type",
            "FIELD_TYPE": 2,
            "FIELD_LENGTH": 10,
            "FIELD_PRECISION": 3,
            "OUTPUT": path_vector_poly_delaunay_typed2
        }
    ) 

    

    if debug:
        from .out_helpers import add_vector

        _ = add_vector(path_vector_poly_delaunay2, "8-Delaunay - Raw Triangles2")
        _ = add_vector(path_vector_poly_delaunay_fixed2, "8-Delaunay - Fixed Triangles2")
        _ = add_vector(path_vector_poly_extents_shrink2, "8-Delaunay - Shrink Mask2")
        _ = add_vector(path_vector_poly_delaunay_clipped2, "8-Delaunay - Clipped Triangles2")
        _ = add_vector(path_vector_poly_delaunay_typed2, "8-Delaunay - Typed Triangles2")


    return path_vector_poly_delaunay_typed2

    



    
    


    
    