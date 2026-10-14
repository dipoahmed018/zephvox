"""Installing, updating and removing speakcheck: `speakcheck setup`, `update`, `uninstall`.

Kept out of the engine: nothing here runs during analysis. Only the core dependencies may be
imported at module level, because setup runs before the models extra is installed.
"""
