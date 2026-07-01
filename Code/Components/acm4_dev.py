# %APPDATA%\QGIS\QGIS3\profiles\default\python\acm4_dev.py

def reload_acm4():
    import sys, importlib
    pkg = "acm4"
    to_drop = [m for m in list(sys.modules) if m == pkg or m.startswith(pkg + ".")]
    for m in to_drop:
        del sys.modules[m]
    importlib.invalidate_caches()
    import acm4  # reload package
    print("[acm4] Reloaded modules:", to_drop)

def refresh_processing_scripts():
    from qgis.core import QgsApplication
    prov = QgsApplication.processingRegistry().providerById("script")
    if prov:
        prov.refreshAlgorithms()
        print("[acm4] Processing scripts refreshed.")

def hot_reload():
    reload_acm4()
    refresh_processing_scripts()
    

