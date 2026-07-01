# acm4/out_helpers.py

from __future__ import annotations
from pathlib import Path
import tempfile
import time
from qgis.core import QgsProject, QgsMapLayer, QgsVectorLayer, QgsRasterLayer, QgsProcessingUtils

# ---------- Choose where your working dir should live ----------

# Option A (default): system temp, independent of QGIS processing_* folders
# _acm4_TEMP = Path(tempfile.gettempdir()) / "acm4_work"
# Option B (if you prefer it under your package folder):
_acm4_TEMP = Path(__file__).parent / "work"

# Create once per import; cheap and idempotent
_acm4_TEMP.mkdir(parents=True, exist_ok=True)

# ---------- Helpers ----------

def _is_layer_opening_this_path(p: Path) -> bool:
    p_norm = str(p).replace("\\", "/")
    for lyr in QgsProject.instance().mapLayers().values():
        if lyr.source().replace("\\", "/") == p_norm:
            return True
    return False

def _try_remove_layer_for_path(p: Path) -> None:
    """Remove any layer mapped to this path, so Windows unlocks the file."""
    project = QgsProject.instance()
    p_norm = str(p).replace("\\", "/")
    ids = [lyr.id() for lyr in project.mapLayers().values()
           if lyr.source().replace("\\", "/") == p_norm]
    for lid in ids:
        project.removeMapLayer(lid)

def _safe_unlink(p: Path, retries: int = 10, delay_s: float = 0.05) -> bool:
    """
    Try to delete a file with small retries (handles laggy GDAL locks on Windows).
    Return True if deleted, False if still locked.
    """
    for _ in range(retries):
        try:
            p.unlink()
            return True
        except PermissionError:
            time.sleep(delay_s)
        except FileNotFoundError:
            return True
    return False

def _unique_suffix() -> str:
    # Timestamp + small counter to avoid collisions
    return str(int(time.time() * 1000))

# ---------- Public API ----------

def _temp_vector(name: str, ext: str = "gpkg", overwrite: bool = True, unique_if_locked: bool = True) -> str:
    """
    Return a temp vector path in our own workspace.

    - If `overwrite=True` and the file is not locked, it will be deleted to ensure a clean dataset.
    - If the file is locked and `unique_if_locked=True`, a unique suffixed filename is returned to avoid the lock.
    - If the file is locked and `unique_if_locked=False`, a PermissionError is raised.

    This avoids the 'file already exists' (OGR) and 'WinError 32' (Windows locking) issues,
    while letting you keep deterministic names when possible.
    """
    ext = ext.lstrip(".").lower()
    base = _acm4_TEMP / f"{name}.{ext}"

    if overwrite and base.exists():
        # If a layer is open on that path, remove it first
        if _is_layer_opening_this_path(base):
            _try_remove_layer_for_path(base)

        # Try to delete old file; if locked, optionally return a new unique name
        if not _safe_unlink(base):
            if unique_if_locked:
                base = _acm4_TEMP / f"{name}_{_unique_suffix()}.{ext}"
            else:
                raise PermissionError(f"Locked file cannot be removed: {base}")

    return str(base)

def _temp_raster(name: str, overwrite: bool = True, unique_if_locked: bool = True) -> str:
    """
    Same policy as _temp_vector() but for GeoTIFF rasters.
    """
    base = _acm4_TEMP / f"{name}.tif"

    if overwrite and base.exists():
        # Rasters can also be locked if added to the project
        if _is_layer_opening_this_path(base):
            _try_remove_layer_for_path(base)
        if not _safe_unlink(base):
            if unique_if_locked:
                base = _acm4_TEMP / f"{name}_{_unique_suffix()}.tif"
            else:
                raise PermissionError(f"Locked file cannot be removed: {base}")

    return str(base)


def _temp_raster(name: str) -> str:
    """
    Deterministic temp filename for rasters in QGIS' temp folder.
    If the file already exists, return it rather than overwriting.
    Avoids GDAL 'file exists' errors during debugging.
    """
    base = Path(QgsProcessingUtils.tempFolder()) / f"{name}.tif"

    # If the raster already exists (common in debugging), just reuse it
    if base.exists():
        return str(base)

    return str(base)

    
def add_raster(layer_path: str, layer_name: str, add_to_legend: bool = True) -> QgsRasterLayer:
    """
    Send the raster layer direct to the visible tree regardless of
    the OUTPUTS of the algorithm.
    """
    
    layer = QgsRasterLayer(layer_path, layer_name)

    if not layer.isValid():
        raise ValueError(f"Raster failed to load: {layer_path}")

    QgsProject.instance().addMapLayer(layer, addToLegend=add_to_legend)

    return layer

    
def add_vector(layer_path: str, layer_name: str, add_to_legend: bool = True) -> QgsVectorLayer:
    """
    Load a vector layer from disk and add it directly to the QGIS project,
    regardless of whether it is an OUTPUT of a processing algorithm.
    Supports any vector provider (GPKG, SHP, GeoJSON, etc.).
    """

    layer = QgsVectorLayer(layer_path, layer_name, "ogr")

    if not layer.isValid():
        raise ValueError(f"Vector layer failed to load: {layer_path}")

    QgsProject.instance().addMapLayer(layer, addToLegend=add_to_legend)

    return layer  


def as_path(obj):
    """
    If 'obj' is a string, return it unchanged.
    If 'obj' is a QgsLayer, return its .source() path.
    Otherwise return None.
    """
    if isinstance(obj, str):
        return obj
    if isinstance(obj, QgsMapLayer):
        return obj.source()
    return None


def safe_save_vector(input_tmp_uri: str, target_uri: str) -> str:
    """
    Ensures the target GeoPackage table is recreated cleanly:
      1) copy INPUT to a brand new temp sink
      2) drop the target layer if it exists
      3) write the fresh contents into the target
    Returns the target_uri.
    """
    import processing

    # 1) solidify the input in a distinct temp sink (breaks any attachment to its producer)
    tmp_copy = processing.run(
        "native:savefeatures",
        {"INPUT": input_tmp_uri, "OVERWRITE": True, "OUTPUT": "TEMPORARY_OUTPUT"}
    )["OUTPUT"]

    # 2) try to drop the existing target layer; ignore if it doesn't exist
    try:
        processing.run("gdal:deletelayer", {"INPUT": target_uri})
    except Exception:
        pass

    # 3) write to the now-free name
    processing.run(
        "native:savefeatures",
        {"INPUT": tmp_copy, "OVERWRITE": True, "OUTPUT": target_uri}
    )
    return target_uri