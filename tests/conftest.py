import os

# The window tests draw off screen: nothing pops up, and no display is needed.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
