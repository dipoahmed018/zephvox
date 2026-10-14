"""Installing, updating and removing zephvox: `zephvox setup`, `update`, `uninstall`.

Kept out of the engine: nothing here runs during analysis. Only the core dependencies may be
imported at module level, because setup runs before the models extra is installed.
"""
