# acm4/basic_grid.py

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
from math import floor, ceil

def do(dtm, polysteep, polyshallow, densesteep, denseshallow, extents_path, debug):
    """
        overlays regular grid points on a polygon mask
        dense value dictates the separation between grid points
        
        inputs : 
            raster dtm for z value promotion
            polygon mask for steep areas,
            polygon mask for steep areas, 
            number (float) for steep grid density,
            number (float) for shallow grid density,
            polygon mask describing the extents
            debug = true outputs all intermediate layers to canvas
        returns :
            vector pointZ layer for steep slopes
            vector pointZ layer for shallow slopes
    """

    from .out_helpers import _temp_vector
    
    path_vector_steepgrid = _temp_vector("acm4_steepgrid")
    path_vector_shallowgrid = _temp_vector("acm4_shallowgrid")
    path_vector_steepgridraw = _temp_vector("acm4_steepgridraw")
    path_vector_shallowgridraw = _temp_vector("acm4_shallowgridraw")
    path_vector_points_steep = _temp_vector("acm4_steeppointsclipped")
    path_vector_points_shallow = _temp_vector("acm4_shallowpointsclipped")
    path_vector_points_steepZ = _temp_vector("acm4_steeppointsclippedZ")
    path_vector_points_shallowZ = _temp_vector("acm4_shallowpointsclippedZ")



    layer = QgsVectorLayer(extents_path, "extent_source", "ogr")
    if not layer.isValid():
        raise Exception(f"Failed to load layer from path: {path}")
    rect = layer.extent()
    grid_crs = layer.crs()
    epsg = grid_crs.postgisSrid()  # e.g., 27700
    
    extent_str = f"{rect.xMinimum()},{rect.xMaximum()},{rect.yMinimum()},{rect.yMaximum()} [EPSG:{epsg}]"

    # create steep and shallow master grids

    result = processing.run("native:creategrid",
        {
            "TYPE": 0,
            "EXTENT": extent_str,
            "HSPACING": densesteep,
            "VSPACING": densesteep,
            
            "HOVERLAY": 0.0,
            "VOVERLAY": 0.0,
            
            "CRS": grid_crs,
            
            "OUTPUT": path_vector_steepgridraw
            }
    )


    result = processing.run("native:creategrid",
        {
            "TYPE": 0,
            "EXTENT": extent_str,
            "HSPACING": denseshallow,
            "VSPACING": denseshallow,
            
            "HOVERLAY": 0.0,
            "VOVERLAY": 0.0,
            
            "CRS": QgsCoordinateReferenceSystem("EPSG:27700"),
            
            "OUTPUT": path_vector_shallowgridraw
            }
    )
 
    # clip master grids by grid masks
    
    result = processing.run("native:intersection",
        {
            "INPUT": path_vector_steepgridraw,
            "OVERLAY": polysteep,
            "INPUT_FIELDS": [],              
            "OVERLAY_FIELDS": [], 
            "GRID_SIZE": 0.001,    
            "OUTPUT": path_vector_points_steep   
        }
    )

    result = processing.run("native:intersection",
        {
            "INPUT": path_vector_shallowgridraw,
            "OVERLAY": polyshallow,
            "INPUT_FIELDS": [],              
            "OVERLAY_FIELDS": [], 
            "GRID_SIZE": 0.001,    
            "OUTPUT": path_vector_points_shallow   
        }
    )

    # promote to z
 
    result = processing.run("native:setzfromraster",
        {
            "INPUT": path_vector_points_steep,
            "RASTER": dtm,
            "BAND": 1,
            "OUTPUT": path_vector_points_steepZ
        }
    )
       
    result = processing.run("native:setzfromraster",
        {
            "INPUT": path_vector_points_shallow,
            "RASTER": dtm,
            "BAND": 1,
            "OUTPUT": path_vector_points_shallowZ
        }
    )
       


    if debug:
        from .out_helpers import add_vector

        _ = add_vector(path_vector_steepgridraw, "3-BasicGrid - SteepGridRaw")
        _ = add_vector(path_vector_shallowgridraw, "3-BasicGrid - ShallowGridRaw")
        _ = add_vector(path_vector_points_steepZ, "3-BasicGrid - SteepGridZ")
        _ = add_vector(path_vector_points_shallowZ, "3-BasicGrid - ShallowGridZ")


    return path_vector_points_steepZ, path_vector_points_shallowZ
