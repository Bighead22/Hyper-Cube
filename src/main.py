#python src/main.py
#pip install cmu-graphics


import math
from cmu_graphics import *

def onAppStart(app):

    app.stepsPerSecond = 120
    
    app.recoil = 0.5
    app.playerAngle = 0
    app.playerX = 375
    app.playerY = 375
    app.playerXSpeed = 0
    app.playerYSpeed = 0
    app.accel = 0.25
    app.drag = 0.99
    
    app.mouseX = 375
    app.mouseY = 375
    
    
    app.bullets = []
    app.bulletSpeed = 15

def onMousePress(app, mouseX, mouseY):
    
    dx = mouseX - app.playerX
    dy = mouseY - app.playerY
    angle = math.atan2(dy, dx)
    
    
    vx = math.cos(angle) * app.bulletSpeed
    vy = math.sin(angle) * app.bulletSpeed
    
    
    app.bullets.append({'x': app.playerX,'y': app.playerY,'vx': vx,'vy': vy})
    app.playerXSpeed -= vx*app.recoil
    app.playerYSpeed -= vy*app.recoil

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
    
    app.playerAngle = math.degrees(math.atan2(dy, dx))
    app.playerX += app.playerXSpeed
    app.playerY += app.playerYSpeed
    app.playerXSpeed *= app.drag
    app.playerYSpeed *= app.drag

    for bullet in app.bullets:
        bullet['x'] += bullet['vx']
        bullet['y'] += bullet['vy']
        
    app.bullets = [b for b in app.bullets if 0 <= b['x'] <= 750 and 0 <= b['y'] <= 750]
    if app.playerX < 0: app.playerX = 750
    if app.playerX > 750: app.playerX = 0
    if app.playerY < 0: app.playerY = 750
    if app.playerY > 750: app.playerY = 0

def trail(app):
    drawRect(app.playerX - app.playerXSpeed * 3-5, app.playerY - app.playerYSpeed * 3-5, 10, 10, fill=rgb(255, 0, 0), opacity=5, border=rgb(255, 255, 255), borderWidth=1, rotateAngle=app.playerAngle)
    drawRect(app.playerX - app.playerXSpeed * 2.5-5, app.playerY - app.playerYSpeed * 2.5-5, 10, 10, fill=rgb(255, 0, 0), opacity=6, border=rgb(255, 255, 255), borderWidth=1, rotateAngle=app.playerAngle)
    drawRect(app.playerX - app.playerXSpeed * 2-5, app.playerY - app.playerYSpeed * 2-5, 10, 10, fill=rgb(255, 0, 0), opacity=7, border=rgb(255, 255, 255), borderWidth=1, rotateAngle=app.playerAngle)
    drawRect(app.playerX - app.playerXSpeed * 1.5-5, app.playerY - app.playerYSpeed * 1.5-5, 10, 10, fill=rgb(255, 0, 0), opacity=8, border=rgb(255, 255, 255), borderWidth=1, rotateAngle=app.playerAngle)
    drawRect(app.playerX - app.playerXSpeed * 1-5, app.playerY - app.playerYSpeed * 1-5, 10, 10, fill=rgb(255, 0, 0), opacity=9, border=rgb(255, 255, 255), borderWidth=1, rotateAngle=app.playerAngle)
    drawRect(app.playerX - app.playerXSpeed * 0.5-5, app.playerY - app.playerYSpeed * 0.5-5, 10, 10, fill=rgb(255, 0, 0), opacity=10, border=rgb(255, 255, 255), borderWidth=1, rotateAngle=app.playerAngle)

def redrawAll(app):
    drawRect(0, 0, 750, 750, fill=rgb(0, 5, 20))
    
    for bullet in app.bullets:
        drawCircle(bullet['x'], bullet['y'], 2, fill=rgb(0, 200, 200),border=rgb(255, 255, 255), borderWidth=1)
        
        #bullet trail
        drawCircle(bullet['x'], bullet['y'], 5, fill=rgb(0, 255, 255), opacity=10)
        drawCircle(bullet['x']-bullet['vx']*0.2, bullet['y']-bullet['vy']*0.2, 4, fill=rgb(0, 255, 255), opacity=8)
        drawCircle(bullet['x']-bullet['vx']*0.4, bullet['y']-bullet['vy']*0.4, 3, fill=rgb(0, 255, 255), opacity=6)
        drawCircle(bullet['x']-bullet['vx']*0.6, bullet['y']-bullet['vy']*0.6, 2, fill=rgb(0, 255, 255), opacity=4)
    
    # Glow trail
    trail(app)
    drawRect(app.playerX - app.playerXSpeed * 0.5-5, app.playerY - app.playerYSpeed * 0.5-5, 10, 10, fill=rgb(255, 0, 0), opacity=10, border=rgb(255, 255, 255), borderWidth=1, rotateAngle=app.playerAngle)
    
    # Player
    drawRect(app.playerX, app.playerY, 10, 10, fill=rgb(255, 0, 0), border=rgb(255, 255, 255), borderWidth=1, align='center', rotateAngle=app.playerAngle)

runApp(width=750, height=750)