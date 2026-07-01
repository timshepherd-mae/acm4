# acm4/form_triang2.py

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

def do(del_tri, del_tri_raised, mask_gdor_0, mask_gdor_1, mask_corr, debug = False ):
    """
        ft2
    """
    from .out_helpers import _temp_vector, add_vector

    # running_gdor_0 = { 
        # _temp_vector("running_gdor_0_" + str(m)) for m in
        # ["WATER", "ROAD", "RAIL", "OTHER", "FOOTPATH", "FOCUS"]
    # }

    typelist = ["WATER", "ROAD", "RAIL", "OTHER", "FOOTPATH", "FOCUS", "FINAL"]
    rungdor0 = [ _temp_vector("rungdor0_" + typelist[n]) for n in [0,1,2,3,4,5,6] ]
    mbts = [ _temp_vector("mbt_" + typelist[n]) for n in [0,1,2,3,4,5,6] ]
    tri_this = [ _temp_vector("tri_this_" + typelist[n]) for n in [0,1,2,3,4,5,6] ]
    tri_rem = [ _temp_vector("tri_rem_" + typelist[n]) for n in [0,1,2,3,4,5,6] ]
    ass_tri = [ _temp_vector("ass_tri_" + typelist[n]) for n in [0,1,2,3,4,5,6] ]

 
    # assign "NORM" to all 'grounded' triangle type fields
    
    running_tri = processing.run("native:fieldcalculator",
        {
            "INPUT": del_tri,
            "FIELD_NAME": "type",
            "FIELD_TYPE": 2,
            "FIELD_LENGTH": 10,
            "FIELD_PRECISION": 3,
            "NEW_FIELD": True,
            "FORMULA": "NORM",
            "OUTPUT": rungdor0[0]
        }
    )

    
    # cycle gdor_0 types
    for n in [0,1,2,3,4,5]:
        mask = typelist[n]
        
        print(f"Step {n} =========== {mask}")
        
        # extract by type
        print(f"Start of step {n}-A=======================")
        mask_by_type = processing.run("native:extractbyattribute",
            {
                "INPUT": mask_gdor_0,
                "FIELD": "type",       
                "OPERATOR": 0,               
                "VALUE": mask,
                "OUTPUT": "TEMPORARY_OUTPUT"
            }
        )["OUTPUT"]
        
        # shrink mask
        # print(f"Start of step {n}-B=======================")
        # mask_by_type_shrink = processing.run("native:buffer",
            # {
                # "INPUT": mask_by_type,
                # "DISTANCE": -0.15,
                # "SEGMENTS": 5,
                # "END_CAP_STYLE": 2,
                # "JOIN_STYLE": 1,
                # "MITER_LIMIT": 2,
                # "DISSOLVE": False,
                # "OUTPUT": "TEMPORARY_OUTPUT"
            # }
        # )["OUTPUT"]
        
        # # get intersecting triangles
        # print(f"Start of step {n}-C=======================")
        # get_tri_by_type = processing.run("native:extractbylocation",
            # {
                # 'INPUT': rungdor0[n],
                # 'PREDICATE': [0],
                # 'INTERSECT': mask_by_type_shrink,
                # 'OUTPUT': "TEMPORARY_OUTPUT"
            # }
        # )["OUTPUT"]

        print(f"Start of step {n}-B=======================")
        mask_by_type_shrink = processing.run("native:buffer",
            {
                "INPUT": mask_by_type,
                "DISTANCE": -0.15,
                "SEGMENTS": 5,
                "END_CAP_STYLE": 2,
                "JOIN_STYLE": 1,
                "MITER_LIMIT": 2,
                "DISSOLVE": False,
                "OUTPUT": mbts[n]
            }
        )

        get_tri_by_type = processing.run("native:extractbylocation",
            {
                'INPUT': rungdor0[n],
                'PREDICATE': [0],
                'INTERSECT': mbts[n],
                'OUTPUT': tri_this[n]
            }
        )


        
        
        # get remaining triangles
        print(f"Start of step {n}-D=======================")
        get_tri_remaining = processing.run("native:extractbylocation",
            {
                'INPUT': rungdor0[n],
                'PREDICATE': [2],
                'INTERSECT': mbts[n],
                'OUTPUT': tri_rem[n]
            }
        )
        
        # assign type attribute
        print(f"Start of step {n}-E=======================")
        assign_type_to_tri = processing.run("native:fieldcalculator",
            {
                "INPUT": tri_this[n],
                "FIELD_NAME": "type",
                "FIELD_TYPE": 2,
                "FIELD_LENGTH": 10,
                "FIELD_PRECISION": 3,
                "NEW_FIELD": False,
                "FORMULA": mask,
                "OUTPUT": ass_tri[n]
            }
        )
        
        # merge back into full tri set
        print(f"Start of step {n}-F=======================")
        running_tri = processing.run("native:mergevectorlayers",
            {
                "LAYERS": [ass_tri[n], tri_rem[n]],
                "OUTPUT": rungdor0[n+1]
            }
        )
        
        _ = add_vector(rungdor0[n], f"rungdor0_{mask}")
        _ = add_vector(mbts[n], f"mbt_{mask}")
        _ = add_vector(tri_this[n], f"tri_this_{mask}")
        _ = add_vector(tri_rem[n], f"tri_rem_{mask}")
        _ = add_vector(ass_tri[n], f"ass_tri_{mask}")

    return del_tri, del_tri_raised

