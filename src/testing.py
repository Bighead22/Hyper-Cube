import pygetwindow as gw
import time
#pip install PyGetWindow
#python src\testing.py

# Give yourself a few seconds to make sure your CMU Graphics window is open

# Find the window by its title (replace "CMU Graphics" with the exact title of your window)
windows = gw.getWindowsWithTitle('main')

if windows:
    win = windows[0]
    
    # Move the window to screen coordinates X=500, Y=200
    win.moveTo(500, 200)
    
    print("Window moved successfully!")
else:
    print("Window not found.")