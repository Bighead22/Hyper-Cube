#python src/main.py
#pip install cmu-graphics

import math
from cmu_graphics import *
app.setMaxShapeCount(160000)

def onAppStart(app):
    app.stepsPerSecond = 60
    
    app.mouseX = 375
    app.mouseY = 375

    app.playerAngle = 0
    app.playerX = 375
    app.playerY = 375
    app.playerXSpeed = 0
    app.playerYSpeed = 0
    app.accel = 0.5
    app.drag = 0.99

    app.maxHp = 100
    app.hp = 100
    app.mag = 12
    app.maxMag = 12
    app.hpRegen = 3000 # lower number for faster regen higher number for slower regen
    
    app.bullets = []
    app.recoilResitance = 1 # get closer to 0 for less recoil higer number for more
    app.bulletSize = 3
    app.recoil = app.bulletSize/9
    app.bulletCount = 1
    app.bulletDamage = 20
    app.bulletSpeed = 30
    app.reload = 0
    app.reloadSpeed = 100
    app.reloading = False
    app.magI = rgb(255,255,255)
    
    # Enemy Setup
    app.enemies = []
    app.enemyspawnCD = 1000 # lower number for faster spawn higher number for slower spawn
    app.enemyCountCD = 1
    app.enemyCount = 1 # Change this to add more enemies
    app.eAccel = 0.75
    app.eDrag = 0.99
    
    # Spawn the enemies
    for i in range(app.enemyCount):
        app.enemies.append({'x': 100 * (i + 1),'y': 100,'hp': 100,'vx': 0,'vy': 0,'angle': 0,'size': 10})
    
    app.gameOverL = ''

def isColiding(app, c1x, c1y, c2x, c2y, hitboxSize):
    if (c2x - hitboxSize <= c1x <= c2x + hitboxSize*2) and (c2y - hitboxSize <= c1y <= c2y + hitboxSize*2):
        return True
    return False

def onMousePress(app, mouseX, mouseY):
    if app.mag != 0.05:
        dx = mouseX - app.playerX
        dy = mouseY - app.playerY
        baseAngle = math.atan2(dy, dx)
        
        spreadAngle = math.radians(5*app.bulletCount)
        
        if app.bulletCount > 1:
            angleStep = spreadAngle / (app.bulletCount - 1)
            startAngle = baseAngle - (spreadAngle / 2)
        else:
            angleStep = 0
            startAngle = baseAngle

        for i in range(app.bulletCount):
            angle = startAngle + (i * angleStep)
            vx = math.cos(angle) * app.bulletSpeed
            vy = math.sin(angle) * app.bulletSpeed
            app.bullets.append({'x': app.playerX, 'y': app.playerY, 'vx': vx, 'vy': vy})
            app.playerXSpeed -= (vx * app.recoil) * app.recoilResitance
            app.playerYSpeed -= (vy * app.recoil) * app.recoilResitance
            i += 1

    if app.mag > 1:
        app.mag-=1
    if app.mag == 1:
        app.mag = 0.05

def onKeyPress(app, key):
    if key == 'r':
        app.reloading = True
    
def onMouseMove(app, mouseX, mouseY):
    app.mouseX = mouseX
    app.mouseY = mouseY

def screenWraping(app):
    # Player wrapping
    if app.playerX < 0: app.playerX = 1000
    if app.playerX > 1000: app.playerX = 0
    if app.playerY < 0: app.playerY = 1000
    if app.playerY > 1000: app.playerY = 0

    # Enemy wrapping
    for enemy in app.enemies:
        if enemy['x'] < 0: enemy['x'] = 1000
        if enemy['x'] > 1000: enemy['x'] = 0
        if enemy['y'] < 0: enemy['y'] = 1000
        if enemy['y'] > 1000: enemy['y'] = 0
    
def onStep(app):
    while len(app.enemies) < app.enemyCount:
        app.enemies.append({'x': 100,'y': 100,'hp': 100,'vx': 0,'vy': 0,'angle': 0,'size': 10})
    
    app.enemyCountCD += 1
    if app.enemyCountCD % app.enemyspawnCD == 0:
        app.enemyCount += 1
    
    app.hp += app.maxHp/app.hpRegen
    if app.hp > app.maxHp:
        app.hp = app.maxHp

    if app.reloading:
        app.magI = None
        app.reload += 1
        if app.reload % 2 == 0:
            app.magI = rgb(255,255,255)
        if app.reload >= app.reloadSpeed:
            app.mag = app.maxMag
            app.reloading = False
            app.reload = 0
            app.magI = rgb(255,255,255)

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

    # Enemy logic - Loop through all enemies
    for enemy in app.enemies:
        ex = ((app.playerX + app.mouseX)/2) - enemy['x']
        ey = ((app.playerY + app.mouseY)/2) - enemy['y']

        eAngle = math.atan2(ey, ex)
        enemy['vx'] += math.cos(eAngle) * app.eAccel
        enemy['vy'] += math.sin(eAngle) * app.eAccel

        enemy['angle'] = math.degrees(math.atan2(ey, ex))
        enemy['x'] += enemy['vx']
        enemy['y'] += enemy['vy']
        enemy['vx'] *= app.eDrag
        enemy['vy'] *= app.eDrag

    # Bullet update and collision
    bulletsToKeep = []
    for bullet in app.bullets:
        bullet['x'] += bullet['vx']
        bullet['y'] += bullet['vy']
        hit = False
        
        # Check collision with each enemy
        for enemy in app.enemies:
            if isColiding(app, bullet['x'], bullet['y'], enemy['x'], enemy['y'], app.bulletSize + enemy['size']):
                enemy['hp'] -= app.bulletDamage
                enemy['vx'] += bullet['vx'] * app.recoil
                enemy['vy'] += bullet['vy'] * app.recoil
                hit = True
                
                # Enemy death/respawn
                if enemy['hp'] <= 1:
                    enemy['hp'] = 0.5
                    enemy['x'] = 1000
                    enemy['y'] = 1000
                    enemy['vx'] = 0
                    enemy['vy'] = 0
                break # Bullet disappears after hitting one enemy
                
        if not hit and 0 <= bullet['x'] <= 1000 and 0 <= bullet['y'] <= 1000:
            bulletsToKeep.append(bullet)
            
    app.bullets = bulletsToKeep
    
    screenWraping(app)
    
    for i in range(len(app.enemies)):
        for j in range(i + 1, len(app.enemies)):
            e1 = app.enemies[i]
            e2 = app.enemies[j]
            
            if isColiding(app, e1['x'], e1['y'], e2['x'], e2['y'], 20):
                # Reverse their directions to bounce
                e1['vx'] *= -1
                e1['vy'] *= -1
                e2['vx'] *= -1
                e2['vy'] *= -1
                
                # Optionally push them slightly apart so they don't get stuck together
                e1['x'] += e1['vx']
                e2['x'] += e2['vx']
    
    # Player vs Enemy collisions
    for enemy in app.enemies:
            
        if isColiding(app, app.playerX, app.playerY, enemy['x'], enemy['y'], enemy['size']):
            app.playerXSpeed += enemy['vx']
            app.playerYSpeed += enemy['vy']
            enemy['vx'] -= app.playerXSpeed*0.75
            enemy['vy'] -= app.playerYSpeed*0.75
            
            impact = math.hypot(math.hypot(enemy['vx'], app.playerXSpeed), math.hypot(enemy['vy'], app.playerYSpeed))/2
            temp = app.hp - impact
            
            if temp > 0:
                app.hp -= impact
            else:
                app.hp = 0.01
    
    if app.hp <= 0.01:
        app.hp = 0.01
        app.gameOverL = 'You lost the game'
        app.stop()

def trail(app):
    # Player trail
    drawRect(app.playerX - app.playerXSpeed * 3-5, app.playerY - app.playerYSpeed * 3-5, 10, 10, fill=rgb(255, 0, 0), opacity=5, border=rgb(255, 255, 255), borderWidth=1, rotateAngle=app.playerAngle)
    drawRect(app.playerX - app.playerXSpeed * 2.5-5, app.playerY - app.playerYSpeed * 2.5-5, 10, 10, fill=rgb(255, 0, 0), opacity=6, border=rgb(255, 255, 255), borderWidth=1, rotateAngle=app.playerAngle)
    drawRect(app.playerX - app.playerXSpeed * 2-5, app.playerY - app.playerYSpeed * 2-5, 10, 10, fill=rgb(255, 0, 0), opacity=7, border=rgb(255, 255, 255), borderWidth=1, rotateAngle=app.playerAngle)
    drawRect(app.playerX - app.playerXSpeed * 1.5-5, app.playerY - app.playerYSpeed * 1.5-5, 10, 10, fill=rgb(255, 0, 0), opacity=8, border=rgb(255, 255, 255), borderWidth=1, rotateAngle=app.playerAngle)
    drawRect(app.playerX - app.playerXSpeed * 1-5, app.playerY - app.playerYSpeed * 1-5, 10, 10, fill=rgb(255, 0, 0), opacity=9, border=rgb(255, 255, 255), borderWidth=1, rotateAngle=app.playerAngle)
    drawRect(app.playerX - app.playerXSpeed * 0.5-5, app.playerY - app.playerYSpeed * 0.5-5, 10, 10, fill=rgb(255, 0, 0), opacity=10, border=rgb(255, 255, 255), borderWidth=1, rotateAngle=app.playerAngle)

    # Enemy trails
    for enemy in app.enemies:
        drawStar(enemy['x'] - enemy['vx'] * 3, enemy['y'] - enemy['vy'] * 3, 20, 3, fill=rgb(255, 255, 0), opacity=5, border=rgb(255, 255, 255), borderWidth=1, roundness=50, rotateAngle=enemy['angle']-90)
        drawStar(enemy['x'] - enemy['vx'] * 2.5, enemy['y'] - enemy['vy'] * 2.5, 20, 3, fill=rgb(255, 255, 0), opacity=6, border=rgb(255, 255, 255), borderWidth=1, roundness=50, rotateAngle=enemy['angle']-90)
        drawStar(enemy['x'] - enemy['vx'] * 2, enemy['y'] - enemy['vy'] * 2, 20, 3, fill=rgb(255, 255, 0), opacity=7, border=rgb(255, 255, 255), borderWidth=1, roundness=50, rotateAngle=enemy['angle']-90)
        drawStar(enemy['x'] - enemy['vx'] * 1.5, enemy['y'] - enemy['vy'] * 1.5, 20, 3, fill=rgb(255, 255, 0), opacity=8, border=rgb(255, 255, 255), borderWidth=1, roundness=50, rotateAngle=enemy['angle']-90)
        drawStar(enemy['x'] - enemy['vx'] * 1, enemy['y'] - enemy['vy'] * 1.5, 20, 3, fill=rgb(255, 255, 0), opacity=9, border=rgb(255, 255, 255), borderWidth=1, roundness=50, rotateAngle=enemy['angle']-90)
        drawStar(enemy['x'] - enemy['vx'] * 0.5, enemy['y'] - enemy['vy'] * 0.5, 20, 3, fill=rgb(255, 255, 0), opacity=10, border=rgb(255, 255, 255), borderWidth=1, roundness=50, rotateAngle=enemy['angle']-90)

def redrawAll(app):
    drawRect(0, 0, 1000, 1000, fill=rgb(0, 5, 20))
    
    for bullet in app.bullets:
        drawCircle(bullet['x'], bullet['y'], app.bulletSize, fill=rgb(0, 200, 200), border=rgb(255, 255, 255), borderWidth=1)
        # Bullet trail
        drawCircle(bullet['x'], bullet['y'], app.bulletSize + 3, fill=rgb(0, 255, 255), opacity=10)
        drawCircle(bullet['x']-bullet['vx']*0.2, bullet['y']-bullet['vy']*0.2, app.bulletSize + 2, fill=rgb(0, 255, 255), opacity=8)
        drawCircle(bullet['x']-bullet['vx']*0.4, bullet['y']-bullet['vy']*0.4, app.bulletSize + 1, fill=rgb(0, 255, 255), opacity=6)
        drawCircle(bullet['x']-bullet['vx']*0.6, bullet['y']-bullet['vy']*0.6, app.bulletSize, fill=rgb(0, 255, 255), opacity=4)
    
    # Glow trails
    trail(app)
    drawRect(app.playerX - app.playerXSpeed * 0.5-5, app.playerY - app.playerYSpeed * 0.5-5, 10, 10, fill=rgb(255, 0, 0), opacity=10, border=rgb(255, 255, 255), borderWidth=1, rotateAngle=app.playerAngle)
    
    # Player
    drawRect(app.playerX, app.playerY, 10, 10, fill=rgb(255, 0, 0), border=rgb(255, 255, 255), borderWidth=1, align='center', rotateAngle=app.playerAngle)
    
    # Enemies
    for enemy in app.enemies:
        drawStar(enemy['x'], enemy['y'], 20, 3, fill=rgb(255, 255, 0), border=rgb(255, 255, 255), borderWidth=1, roundness=50, rotateAngle=enemy['angle']-90)
        # Enemy health bar
        drawRect(enemy['x'], enemy['y'] + 15, enemy['hp']*0.2, 3, fill=rgb(0, 255, 0), align='center') 
        
    # UI: Health
    drawRect(10, 10, app.maxHp*2+4, 24, fill=rgb(255, 255, 255))
    drawRect(12, 12, app.hp*2, 20, fill='lime')
    # UI: Mag
    drawRect(10, 44, app.maxMag*10+4, 24, fill=app.magI)
    drawRect(12, 46, app.mag*10, 20, fill='teal')
    
    # Game over
    if app.gameOverL:
        drawLabel(app.gameOverL, 500, 500, size=50, fill=rgb(255, 0, 0), bold=True, border=rgb(255, 255, 255), borderWidth=1)

runApp(width=1000, height=1000)