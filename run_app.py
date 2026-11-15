"""Launch the shuffle solver window (also the PyInstaller entry point)."""

import multiprocessing

if __name__ == "__main__":
    # In the packaged app, a search process starts as another copy of this exe:
    # this runs its search and exits before any window code is imported.
    multiprocessing.freeze_support()
    from shuffle_solver.ui.app import main

    main()
