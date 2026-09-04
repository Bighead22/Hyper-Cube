#python main.py
import math
from cmu_graphics import *

def onAppStart(app):
    app.stepsPerSecond = 60
    app.playerX = 200
    app.playerY = 200
    app.playerXSpeed = 0
    app.playerYSpeed = 0
    app.accel = 0.5
    app.drag = 0.995
    
    app.mouseX = 200
    app.mouseY = 200
    
def onMousePress(app, mouseX, mouseY):
    app.playerX = mouseX
    app.playerY = mouseY

def onMouseMove(app, mouseX, mouseY):
    app.mouseX = mouseX
    app.mouseY = mouseY
    
def onStep(app):
    
    dx = app.mouseX - app.playerX
    dy = app.mouseY - app.playerY
    dist = math.hypot(dx, dy)
        
    if dist > 5:
        angle = math.atan2(dy, dx)
        app.playerXSpeed += math.cos(angle) * app.accel
        app.playerYSpeed += math.sin(angle) * app.accel
    
    # Apply position updates
    app.playerX += app.playerXSpeed
    app.playerY += app.playerYSpeed
    app.playerXSpeed *= app.drag
    app.playerYSpeed *= app.drag

def redrawAll(app):
    drawRect(0, 0, 400, 400, fill=rgb(0, 5, 20))
    
    # glow3
    drawOval(app.playerX-app.playerXSpeed*4, app.playerY-app.playerYSpeed*4, 20, 20, fill=rgb(255, 0, 0), opacity=10)
    
    # glow2
    drawOval(app.playerX-app.playerXSpeed*2, app.playerY-app.playerYSpeed*2, 20, 20, fill=rgb(255, 0, 0), opacity=10)
    
    # glow1
    drawOval(app.playerX-app.playerXSpeed*0.5, app.playerY-app.playerYSpeed*0.5, 20, 20, fill=rgb(255, 0, 0), opacity=10)
    
    # Player
    drawRect(app.playerX, app.playerY, 10, 10, fill=rgb(255, 0, 0), 
             border=rgb(255, 255, 255), borderWidth=1, align='center')

runApp(width=400, height=400)