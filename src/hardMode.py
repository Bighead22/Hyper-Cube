import pygetwindow as gw
import time
import random
#python src//hardMode.py

windows = gw.getWindowsWithTitle('main')
windowX = 0
speed = 1

if windows:
    win = windows[0]
    while True:
        win.moveTo(windowX, 0)
        windowX += 1*speed
        if windowX > 900 or windowX < 0:
            speed *= -1
    
    print("Window moved successfully!")
else:
    print("Window not found.")