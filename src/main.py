#python main.py
import math
from cmu_graphics import *

def onAppStart(app):
    app.stepsPerSecond = 30
    app.playerX = 375
    app.playerY = 375
    app.playerXSpeed = 0
    app.playerYSpeed = 0
    app.accel = 0.5
    app.drag = 0.995
    
    app.mouseX = 375
    app.mouseY = 375
    
    # Store active projectiles
    app.bullets = []
    app.bulletSpeed = 15

def onMousePress(app, mouseX, mouseY):
    # Calculate vector from player to mouse at click time
    dx = mouseX - app.playerX
    dy = mouseY - app.playerY
    angle = math.atan2(dy, dx)
    
    # Calculate velocity components
    vx = math.cos(angle) * app.bulletSpeed
    vy = math.sin(angle) * app.bulletSpeed
    
    # Add projectile starting at player position
    app.bullets.append({'x': app.playerX,'y': app.playerY,'vx': vx,'vy': vy})
    app.playerXSpeed -= vx*0.2
    app.playerYSpeed -= vy*0.2

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
    
    app.playerX += app.playerXSpeed
    app.playerY += app.playerYSpeed
    app.playerXSpeed *= app.drag
    app.playerYSpeed *= app.drag

    for bullet in app.bullets:
        bullet['x'] += bullet['vx']
        bullet['y'] += bullet['vy']
        
    app.bullets = [b for b in app.bullets if 0 <= b['x'] <= 750 and 0 <= b['y'] <= 750]
    if app.playerX < 25: app.playerX = 25
    if app.playerX > 725: app.playerX = 725
    if app.playerY < 25: app.playerY = 25
    if app.playerY > 725: app.playerY = 725

def redrawAll(app):
    drawRect(0, 0, 750, 750, fill=rgb(0, 5, 20))
    
    for bullet in app.bullets:
        drawCircle(bullet['x'], bullet['y'], 2, fill=rgb(255, 255, 0))
        drawCircle(bullet['x'], bullet['y'], 5, fill=rgb(255, 255, 0), opacity=10)
    
    # Glow trail
    drawOval(app.playerX - app.playerXSpeed * 3, app.playerY - app.playerYSpeed * 3, 20, 20, fill=rgb(255, 0, 0), opacity=10)
    drawOval(app.playerX - app.playerXSpeed * 2, app.playerY - app.playerYSpeed * 2, 20, 20, fill=rgb(255, 0, 0), opacity=10)
    drawOval(app.playerX - app.playerXSpeed * 1, app.playerY - app.playerYSpeed * 1, 20, 20, fill=rgb(255, 0, 0), opacity=10)
    
    # Player
    drawRect(app.playerX, app.playerY, 10, 10, fill=rgb(255, 0, 0), 
             border=rgb(255, 255, 255), borderWidth=1, align='center')

runApp(width=750, height=750)