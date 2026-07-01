# -*- coding: utf-8 -*-
"""
auto_context_modeller_4 (acm4) – QGIS 3.44 safe Processing script

Inputs:
  - DTM raster (QgsRasterLayer)
  - DSM raster (QgsRasterLayer)
  - EXTENT polygon layer (QgsVectorLayer)
  - Integer "Process Depth" (used to control number of algorithm steps taken)

Outputs:
  - Clipped DTM raster
  - Clipped DSM raster

Notes (safe imports):
  - This script does NOT modify sys.path (prevents recursion explosions).
  - Ensure your helpers are importable by Python:
      • Install as a package, OR
      • Add a .pth file in site-packages pointing to your helpers folder, OR
      • Add the folder once in %APPDATA%/QGIS/QGIS3/.../python/startup.py
"""

import sys, os
from pathlib import Path


import processing
from qgis.core import QgsApplication
from processing.core.Processing import Processing

Processing.initialize()

from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterNumber,
    QgsProcessingOutputRasterLayer,
    QgsProcessingOutputVectorLayer,
    QgsFeatureRequest,
    QgsGeometry, 
    QgsWkbTypes, 
    QgsFeature, 
    QgsFeatureSink,
    QgsPointXY,
    QgsFeatureRequest,
    QgsProcessingMultiStepFeedback, 
    QgsMessageLog,
    Qgis,
)
from qgis.PyQt.QtCore import QCoreApplication


class auto_context_modeller_4(QgsProcessingAlgorithm):
    """

    """

    DEBUG = True
    DEBUG_START = 0
    DEBUG_END = 3

    # --- Parameter / Output keys (stable IDs used internally) ---
    INPUT_RASTER_DTM = "INPUT_RASTER_DTM"
    INPUT_RASTER_DSM = "INPUT_RASTER_DSM"
    INPUT_POLYGON_EXTENT = "INPUT_POLYGON_EXTENT"
    INPUT_LINE_CORRIDOR = "INPUT_LINE_CORRIDOR"
    INPUT_POLYGON_GRIDOVER = "INPUT_POLYGON_GRIDOVER"
    
    # OUTPUT_RASTER_DTM_CLIPPED = "OUTPUT_RASTER_DTM_CLIPPED"
    # OUTPUT_RASTER_DSM_CLIPPED = "OUTPUT_RASTER_DSM_CLIPPED"
    # OUTPUT_POLYGON_EXT_OFFSET = "OUTPUT_POLYGON_EXT_OFFSET"

    OUTPUT_POLYGON_NETWORK_GROUNDED = "OUTPUT_POLYGON_NETWORK_GROUNDED"
    OUTPUT_POLYGON_NETWORK_RAISED = "OUTPUT_POLYGON_NETWORK_RAISED"
    

    PARAM_SLOPEMASK_LIMIT = "PARAM_SLOPEMASK_LIMIT"

    PARAM_STEEP_GRID_DENSE = "PARAM_STEEP_GRID_DENSE"
    PARAM_SHALLOW_GRID_DENSE = "PARAM_SHALLOW_GRID_DENSE"
    
    PARAM_DEBUG_START = "PARAM_DEBUG_START"
    PARAM_DEBUG_END = "PARAM_DEBUG_END"
    PARAM_DEBUG_BAIL = "PARAM_DEBUG_BAIL"
     

    # -------------------------
    # Required algorithm metadata
    # -------------------------
    def tr(self, string):
        """Convenience for translations."""
        return QCoreApplication.translate("auto_context_modeller_4", string)

    def name(self):
        """Algorithm id (unique, lowercase, no spaces)."""
        return "auto_context_modeller_4"

    def displayName(self):
        """Human-readable name."""
        return self.tr("Auto Context Modeller for QGIS4.0")

    def group(self):
        """Grouping label in the toolbox."""
        return self.tr("ACM4")

    def groupId(self):
        """Grouping id (unique, lowercase)."""
        return "examples"

    def shortHelpString(self):
        return self.tr(
            "Auto Context Modeller for QGIS4.0"
        )

    # -------------------------
    # Constructor
    # -------------------------
    def __init__(self):
        super().__init__()

    # -------------------------
    # Parameter & output declarations
    # -------------------------
    def initAlgorithm(self, config=None):
        # Inputs
        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.INPUT_RASTER_DTM,
                self.tr("Input DTM")
            )
        )

        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.INPUT_RASTER_DSM,
                self.tr("Input DSM")
            )
        )

        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.INPUT_POLYGON_EXTENT,
                self.tr("Input EXTENT"),
                [QgsProcessing.TypeVectorPolygon]
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.PARAM_SLOPEMASK_LIMIT,
                self.tr("Slopemask Angle Threshold"),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=4.25,     # optional
                minValue=0,          # optional
                maxValue=90         # optional
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.PARAM_STEEP_GRID_DENSE,
                self.tr("Grid Density of steep slopes"),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=4,     # optional
                minValue=1,          # optional
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.PARAM_SHALLOW_GRID_DENSE,
                self.tr("Grid Density of shallow slopes"),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=20,     # optional
                minValue=1,          # optional
            )
        )

        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.INPUT_LINE_CORRIDOR,
                self.tr("Input CORRIDORS"),
                [QgsProcessing.TypeVectorLine]
            )
        )

        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.INPUT_POLYGON_GRIDOVER,
                self.tr("Input GRID OVERRIDES"),
                [QgsProcessing.TypeVectorPolygon]
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.PARAM_DEBUG_START,
                self.tr("Debug Output Layers From Step"),
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=1,     # optional
                minValue=1,          # optional
                maxValue=10         # optional
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.PARAM_DEBUG_END,
                self.tr("Debug Output Layers To Step"),
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=10,     # optional
                minValue=1,          # optional
                maxValue=10         # optional
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.PARAM_DEBUG_BAIL,
                self.tr("Terminate Process At Step"),
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=10,     # optional
                minValue=1,          # optional
                maxValue=10         # optional
            )
        )


        # Outputs
        self.addOutput(
            QgsProcessingOutputVectorLayer(
                self.OUTPUT_POLYGON_NETWORK_GROUNDED,
                self.tr("Network (grounded)")
            )
        )

        self.addOutput(
            QgsProcessingOutputVectorLayer(
                self.OUTPUT_POLYGON_NETWORK_RAISED,
                self.tr("Network (raised)")
            )
        )



    # -------------------------
    # The core logic
    # -------------------------
    def processAlgorithm(self, parameters, context, feedback):

        
        from acm4 import raster_prep as rp
        from acm4 import slope_mask as sm
        from acm4 import basic_grid as bg
        from acm4 import slope_grid as sg
        from acm4 import ndsm_mask as nm
        from acm4 import corridors as cr
        from acm4 import grid_overrides as go
        from acm4 import feat_merge as fm
        from acm4 import delaunay as dl
        from acm4 import form_triang as ft
        from acm4 import out_helpers as oh
        
        # Retrieve inputs
        layer_in_dtm = self.parameterAsRasterLayer(parameters, self.INPUT_RASTER_DTM, context)
        layer_in_dsm = self.parameterAsRasterLayer(parameters, self.INPUT_RASTER_DSM, context)
        layer_in_extents = self.parameterAsVectorLayer(parameters, self.INPUT_POLYGON_EXTENT, context)
        param_slopemask_limit = self.parameterAsInt(parameters, self.PARAM_SLOPEMASK_LIMIT, context)
        param_grid_steep_dense = self.parameterAsInt(parameters, self.PARAM_STEEP_GRID_DENSE, context)
        param_grid_shallow_dense = self.parameterAsInt(parameters, self.PARAM_SHALLOW_GRID_DENSE, context)
        layer_in_corridor = self.parameterAsVectorLayer(parameters, self.INPUT_LINE_CORRIDOR, context)
        layer_in_gridover = self.parameterAsVectorLayer(parameters, self.INPUT_POLYGON_GRIDOVER, context)
        param_debug_start = self.parameterAsInt(parameters, self.PARAM_DEBUG_START, context)
        param_debug_end = self.parameterAsInt(parameters, self.PARAM_DEBUG_END, context)
        param_debug_bail = self.parameterAsInt(parameters, self.PARAM_DEBUG_BAIL, context)
        

        if layer_in_dtm is None:
            raise QgsProcessingException(self.tr("Invalid DTM input."))
        if layer_in_dsm is None:
            raise QgsProcessingException(self.tr("Invalid DSM input."))
        if layer_in_extents is None:
            raise QgsProcessingException(self.tr("Invalid EXTENT input."))
       


    # -------------------------
    # Main Sequence
    # -------------------------
        

    # -------------------------
    # 1 - Raster Preparation
    # -------------------------
        feedback.pushInfo("Raster Preparation")
        
        path_raster_dtm, path_raster_dsm, path_raster_ndsm, path_raster_slope, path_mask_clip = rp.do(    
            layer_in_dtm, 
            layer_in_dsm, 
            layer_in_extents, 
            debug = (param_debug_start <= 1 and param_debug_end >= 1)
        )
        if (param_debug_bail == 1):
            return {}

    # # -------------------------
    # # 2 - Slope Masking
    # # -------------------------

        # path_vector_steeppoly, path_vector_shallowpoly = sm.do(    
            # path_raster_slope, 
            # param_slopemask_limit,
            # path_mask_clip,
            # debug = (param_debug_start <= 2 and param_debug_end >= 2)
        # )
        # if (param_debug_bail == 2):
            # return {}


    # # -------------------------
    # # 3 - Basic Grid Points
    # # -------------------------

        # path_vector_gridpoints_steep, path_vector_gridpoints_shallow = bg.do(
            # path_raster_dtm,
            # path_vector_steeppoly,
            # path_vector_shallowpoly,
            # param_grid_steep_dense,
            # param_grid_shallow_dense,
            # path_mask_clip,
            # debug = (param_debug_start <= 3 and param_debug_end >= 3)
        # )





    # -------------------------
    # 2.5 - Slope Grids
    # -------------------------
        feedback.pushInfo("Creating Slope Grids")

        path_vector_gridpoints_steep, path_vector_gridpoints_shallow = sg.do(
            path_raster_slope,
            path_raster_dtm,
            path_mask_clip,
            param_slopemask_limit,
            param_grid_steep_dense,
            param_grid_shallow_dense,
            debug = (param_debug_start <= 3 and param_debug_end >= 3)
        )
        if (param_debug_bail == 3):
            return {}

    # -------------------------
    # 4 - nDSM Masking
    # -------------------------
        feedback.pushInfo("Creating nDSM Mask")

        path_vector_high_poly = nm.do(
            path_raster_ndsm,
            0.25,
            debug = (param_debug_start <= 4 and param_debug_end >= 4)
        )
        if (param_debug_bail == 4):
            return {}


    # -------------------------
    # 5 - Corridors
    # -------------------------
        feedback.pushInfo("Calculating Corridors")

        (
            path_vector_corr_points_low,
            path_vector_corr_lines_low,
            path_vector_corr_poly_low,
            path_vector_corr_points_high,
            path_vector_corr_lines_high,
            path_vector_corr_poly_high
        ) = cr.do( 
            path_raster_dtm,
            path_raster_dsm,
            layer_in_corridor,
            path_vector_high_poly,
            param_grid_steep_dense,
            debug = (param_debug_start <= 5 and param_debug_end >= 5)
        )
        if (param_debug_bail == 5):
            return {}


    # -------------------------
    # 6 - Grid Overrides
    # -------------------------
        feedback.pushInfo("Calculating Grid Overrides")

        (
            path_vector_gdor_points,
            path_vector_gdor_lines,
            path_vector_gdor_poly
        ) = go.do(
            layer_in_gridover,
            path_raster_dtm,
            path_raster_dsm,
            debug = (param_debug_start <= 6 and param_debug_end >= 6)
        )
        if (param_debug_bail == 6):
            return {}


    # -------------------------
    # 7 - Feature Merge
    # -------------------------
        feedback.pushInfo("Merging Features")

        (
            path_vector_delpoints_grounded,
            path_vector_delbreaks_grounded
        ) = fm.do(
            path_vector_gridpoints_steep,
            path_vector_gridpoints_shallow,
            path_vector_gdor_points,
            path_vector_gdor_lines,
            path_vector_gdor_poly,
            path_vector_corr_points_low,
            path_vector_corr_lines_low,
            path_vector_corr_poly_low,
            layer_in_extents,
            path_raster_dtm,
            debug = (param_debug_start <= 7 and param_debug_end >= 7)
        )
        if (param_debug_bail == 7):
            return {}


    # -------------------------
    # 8 - Delaunay
    # -------------------------
        feedback.pushInfo("Creating Delaunay Triangulation")

        path_vector_delaunay_grounded = dl.do_one(
            path_vector_delpoints_grounded,
            path_vector_delbreaks_grounded,
            layer_in_extents,
            debug = (param_debug_start <= 8 and param_debug_end >= 8)
        )
        path_vector_delaunay_raised = dl.do_two(
            path_vector_corr_points_high,
            path_vector_corr_lines_high,
            path_vector_corr_poly_high,
            debug = (param_debug_start <= 8 and param_debug_end >= 8)
        )

        if (param_debug_bail == 8):
            return {}


    # -------------------------
    # 9 - Format Triangles
    # -------------------------
        feedback.pushInfo("Formatting Triangles")
        
        network_grounded, network_raised = ft.do(
            del_tri = path_vector_delaunay_grounded,
            del_tri_raised = path_vector_delaunay_raised,
            gdor_mask = path_vector_gdor_poly,
            corr_mask = path_vector_corr_poly_low,
            debug = (param_debug_start <= 9 and param_debug_end >= 9)
        )




    # -------------------------
    # ALGORITHM OUTPUTS
    # -------------------------

        results = {
            self.OUTPUT_POLYGON_NETWORK_GROUNDED: network_grounded,
            self.OUTPUT_POLYGON_NETWORK_RAISED: network_raised
        }
            
        
        return results

    # -------------------------
    # Helper(s)
    # -------------------------



    @staticmethod
    def layer_signature(layer):
        return layer.fields(), layer.wkbType(), layer.sourceCrs()



    # -------------------------
    # Factory
    # -------------------------
    def createInstance(self):
        return auto_context_modeller_4()
