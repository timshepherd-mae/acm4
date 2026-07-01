# acm4/form_triang.py

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

def do(del_tri, del_tri_raised = None, gdor_mask = None, corr_mask = None, debug = False ):
    """

    """
    from .out_helpers import _temp_vector, add_vector
    
    gdor_mask_out = {}
    gdor_extract_out = {}
    gdor_tagged_out = {}
    
    corr_mask_out = {}
    corr_extract_out = {}
    corr_tagged_out = {}
    
    path_vector_gdor_shrink = _temp_vector("acm4_gdor_shrink")
    path_vector_corr_shrink = _temp_vector("acm4_corr_shrink")

    path_vector_corr_tri_only = _temp_vector("acm4_corr_tri_only")
    path_vector_corr_tri_inv = _temp_vector("acm4_corr_tri_inv")
    
    path_vector_gdor_tri_only = _temp_vector("acm4_gdor_tri_only")
    path_vector_gdor_tri_inv = _temp_vector("acm4_gdor_tri_inv")

    norm_tagged_out = _temp_vector("acm4_norm_tagged_out")
    network_raised = _temp_vector("acm4_network_raised")

    network_grounded = _temp_vector("network_grounded")

    tmpv = _temp_vector("tmpv")

    # shrink the masks
    
    result = processing.run("native:buffer",
        {
            "INPUT": gdor_mask,
            "DISTANCE": -0.5,
            "SEGMENTS": 5,
            "END_CAP_STYLE": 2,
            "JOIN_STYLE": 1,
            "MITER_LIMIT": 2,
            "DISSOLVE": False,
            "OUTPUT": path_vector_gdor_shrink
        }
    )
    result = processing.run("native:buffer",
        {
            "INPUT": corr_mask,
            "DISTANCE": -0.5,
            "SEGMENTS": 5,
            "END_CAP_STYLE": 2,
            "JOIN_STYLE": 1,
            "MITER_LIMIT": 2,
            "DISSOLVE": False,
            "OUTPUT": path_vector_corr_shrink
        }
    )


    # separate shrink masks by type attribute

    for masktype in ["WATER", "ROAD", "RAIL", "OTHER", "FOOTPATH", "FOCUS"]:
        
        gdor_mask_out[masktype] = _temp_vector(f"acm4_mask_gdor_{masktype}")
        corr_mask_out[masktype] = _temp_vector(f"acm4_mask_corr_{masktype}")

        gdor_tagged_out[masktype] = _temp_vector(f"acm4_tagged_gdor_{masktype}")
        corr_tagged_out[masktype] = _temp_vector(f"acm4_tagged_corr_{masktype}")


        result = processing.run("native:extractbyattribute",
            {
                "INPUT": path_vector_gdor_shrink,
                "FIELD": "type",       
                "OPERATOR": 0,               
                "VALUE": masktype,
                "OUTPUT": gdor_mask_out[masktype]
            }
        )
        result = processing.run("native:extractbyattribute",
            {
                "INPUT": path_vector_corr_shrink,
                "FIELD": "type",       
                "OPERATOR": 0,               
                "VALUE": masktype,
                "OUTPUT": corr_mask_out[masktype]
            }
        )

    # isolate and remove corridor triangles

    result = processing.run("native:extractbylocation",
        {
            'INPUT': del_tri,
            'PREDICATE': [0],
            'INTERSECT': path_vector_corr_shrink,
            'OUTPUT': path_vector_corr_tri_only
        }
    )
    result = processing.run("native:extractbylocation",
        {
            'INPUT': del_tri,
            'PREDICATE': [2],
            'INTERSECT': path_vector_corr_shrink,
            'OUTPUT': path_vector_corr_tri_inv
        }
    )
    
    # isolate and remove gridoverride triangles

    result = processing.run("native:extractbylocation",
        {
            'INPUT': path_vector_corr_tri_inv,
            'PREDICATE': [0],
            'INTERSECT': path_vector_gdor_shrink,
            'OUTPUT': path_vector_gdor_tri_only
        }
    )
    result = processing.run("native:extractbylocation",
        {
            'INPUT': path_vector_corr_tri_inv,
            'PREDICATE': [2],
            'INTERSECT': path_vector_gdor_shrink,
            'OUTPUT': path_vector_gdor_tri_inv
        }
    )
    
    # iterate through corridor masks to extract and tag corridor triangles
    
    for masktype in ["WATER", "ROAD", "RAIL", "OTHER", "FOOTPATH", "FOCUS"]:

        corr_extract_out[masktype] = _temp_vector(f"acm4_extract_corr_{masktype}")

        
        result = processing.run("native:extractbylocation",
            {
                'INPUT': path_vector_corr_tri_only,
                'PREDICATE': [0],
                'INTERSECT': corr_mask_out[masktype],
                'OUTPUT': corr_extract_out[masktype]
            }
        )
        result = processing.run("native:fieldcalculator",
            {
                "INPUT": corr_extract_out[masktype],
                "FIELD_NAME": "type",
                "FIELD_TYPE": 2,
                "FIELD_LENGTH": 10,
                "FIELD_PRECISION": 3,
                "NEW_FIELD": False,
                "FORMULA": f"'{masktype}'",
                "OUTPUT": corr_tagged_out[masktype]
            }
        )
        
    # iterate through gridoverride masks to extract and tag corridor triangles
    
    for masktype in ["WATER", "ROAD", "RAIL", "OTHER", "FOOTPATH", "FOCUS"]:

        gdor_extract_out[masktype] = _temp_vector(f"acm4_extract_gdor_{masktype}")

        
        result = processing.run("native:extractbylocation",
            {
                'INPUT': path_vector_gdor_tri_only,
                'PREDICATE': [0],
                'INTERSECT': gdor_mask_out[masktype],
                'OUTPUT': gdor_extract_out[masktype]
            }
        )
        result = processing.run("native:fieldcalculator",
            {
                "INPUT": gdor_extract_out[masktype],
                "FIELD_NAME": "type",
                "FIELD_TYPE": 2,
                "FIELD_LENGTH": 10,
                "FIELD_PRECISION": 3,
                "NEW_FIELD": False,
                "FORMULA": f"'{masktype}'",
                "OUTPUT": gdor_tagged_out[masktype]
            }
        )

    # tag remaining triangles as "NORM"
        
    result = processing.run("native:fieldcalculator",
        {
            "INPUT": path_vector_gdor_tri_inv,
            "FIELD_NAME": "type",
            "FIELD_TYPE": 2,
            "FIELD_LENGTH": 10,
            "FIELD_PRECISION": 3,
            "NEW_FIELD": False,
            "FORMULA": "'NORM'",
            "OUTPUT": norm_tagged_out
        }
    )

    if del_tri_raised:
        # tag del_tri2 triangles as "OVER"
        result = processing.run("native:fieldcalculator",
            {
                "INPUT": del_tri_raised,
                "FIELD_NAME": "type",
                "FIELD_TYPE": 2,
                "FIELD_LENGTH": 10,
                "FIELD_PRECISION": 3,
                "NEW_FIELD": False,
                "FORMULA": "'OVER'",
                "OUTPUT": network_raised
            }
        )
    else:
        network_raised = ""


    # merge all grounded layers
    
    result = processing.run(
        "native:mergevectorlayers",
        {
            'LAYERS':
                [
                    gdor_tagged_out["WATER"],
                    gdor_tagged_out["ROAD"],
                    gdor_tagged_out["RAIL"],
                    gdor_tagged_out["OTHER"],
                    gdor_tagged_out["FOOTPATH"],
                    gdor_tagged_out["FOCUS"],
                    corr_tagged_out["WATER"],
                    corr_tagged_out["ROAD"],
                    corr_tagged_out["RAIL"],
                    corr_tagged_out["OTHER"],
                    corr_tagged_out["FOOTPATH"],
                    corr_tagged_out["FOCUS"],
                    norm_tagged_out
                ],
            'CRS': None,
            'OUTPUT': network_grounded
        }
    )

    uri_grounded = f"{network_grounded}|layername=grounded"
    uri_raised = f"{network_raised}|layername=raised"

    from .out_helpers import add_vector
    if debug:
        add_vector(network_grounded, "FINAL NETWORK (debug-8)")
        if del_tri_raised:
            add_vector(network_raised, "FINAL OVERPASS (debug-8)")
        

            #add_vector(path_vector_gdor_shrink, "9-Formatting - gdor_shrink")
            #add_vector(path_vector_corr_shrink, "9-Formatting - corr_shrink")
     
            #add_vector(path_vector_corr_tri_only, "9-Formatting - corr_tri_only")
            #add_vector(path_vector_corr_tri_inv, "9-Formatting - corr_tri_inv")
            #add_vector(path_vector_gdor_tri_only, "9-Formatting - gdor_tri_only")
            #add_vector(norm_tagged_out, "9-Formatting - norm_tagged")
     
            
            # for masktype in ["WATER", "ROAD", "RAIL", "OTHER"]:
                # #add_vector(corr_extract_out[masktype] , f"9-Formatting - corr_extract_{masktype}")
                # add_vector(corr_tagged_out[masktype] , f"9-Formatting - corr_tagged_{masktype}")

                # #add_vector(gdor_extract_out[masktype] , f"9-Formatting - gdor_extract_{masktype}")
                # add_vector(gdor_tagged_out[masktype] , f"9-Formatting - gdor_tagged_{masktype}")
                

    return network_grounded, network_raised

