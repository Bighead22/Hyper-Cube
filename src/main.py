#python src/main.py
#pip install cmu-graphics

from cmu_graphics import *
import math
import random
import stats
import logicFunctions

app.setMaxShapeCount(160000)

def onAppStart(app):

    app.stepsPerSecond = 60

def onMousePress(app, mouseX, mouseY):
    if stats.mag != 0.05:
        dx = mouseX - stats.playerX
        dy = mouseY - stats.playerY
        baseAngle = math.atan2(dy, dx)
        
        spreadAngle = math.radians(5*stats.bulletCount)
        
        if stats.bulletCount > 1:
            angleStep = spreadAngle / (stats.bulletCount - 1)
            startAngle = baseAngle - (spreadAngle / 2)
        else:
            angleStep = 0
            startAngle = baseAngle

        for i in range(stats.bulletCount):
            angle = startAngle + (i * angleStep)
            vx = math.cos(angle) * stats.bulletSpeed
            vy = math.sin(angle) * stats.bulletSpeed
            stats.bullets.append({'x': stats.playerX, 'y': stats.playerY, 'vx': vx, 'vy': vy})
            stats.playerXSpeed -= (vx * stats.recoil) * stats.recoilResitance
            stats.playerYSpeed -= (vy * stats.recoil) * stats.recoilResitance
            i += 1

    if stats.mag > 1:
        stats.mag-=1
    if stats.mag == 1:
        stats.mag = 0.05

def onKeyPress(app, key):
    if key == 'r':
        stats.reloading = True
    
def onMouseMove(app, mouseX, mouseY):
    stats.mouseX = mouseX
    stats.mouseY = mouseY

def screenWraping(app):
    # Player wrapping
    if stats.playerX < 0: stats.playerX = 1000
    if stats.playerX > 1000: stats.playerX = 0
    if stats.playerY < 0: stats.playerY = 1000
    if stats.playerY > 1000: stats.playerY = 0

    # Enemy wrapping
    for enemy in stats.enemies:
        if enemy['x'] < 0: enemy['x'] = 1000
        if enemy['x'] > 1000: enemy['x'] = 0
        if enemy['y'] < 0: enemy['y'] = 1000
        if enemy['y'] > 1000: enemy['y'] = 0
    
def onStep(app):
    #app.enemyType = random.randint(0, 1)
    stats.score += 1/30
    while len(stats.enemies) < stats.enemyCount:
        stats.enemies.append({'x': 100,'y': 100,'hp': random.randint(100, 200) * stats.enemyHpMultiplier,'vx': 0,'vy': 0,'angle': 0,'size': 10, 'type' : random.randint(1,2), 'speed' : 0.75})
    for enemy in stats.enemies:
        if enemy['type'] == 1:
            enemy['size'] = 15
            enemy['speed'] = 0.75
        if enemy['type'] == 2:
            enemy['size'] = 5
            enemy['speed'] = 1.25

    stats.enemyCountCD += 1
    if stats.enemyCountCD % stats.enemyspawnCD == 0:
        stats.enemyCount += 1
    
    stats.hp += stats.maxHp/stats.hpRegen
    if stats.hp > stats.maxHp:
        stats.hp = stats.maxHp

    if stats.reloading:
        stats.magI = None
        stats.reload += 1
        if stats.reload % 2 == 0:
            stats.magI = rgb(255,255,255)
        if stats.reload >= stats.reloadSpeed:
            stats.mag = stats.maxMag
            stats.reloading = False
            stats.reload = 0
            stats.magI = rgb(255,255,255)

    dx = stats.mouseX - stats.playerX
    dy = stats.mouseY - stats.playerY
    dist = math.hypot(dx, dy)
        
    if dist > 5:
        angle = math.atan2(dy, dx)
        stats.playerXSpeed += math.cos(angle) * stats.accel
        stats.playerYSpeed += math.sin(angle) * stats.accel
    
    stats.playerAngle = math.degrees(math.atan2(dy, dx))
    stats.playerX += stats.playerXSpeed
    stats.playerY += stats.playerYSpeed
    stats.playerXSpeed *= stats.drag
    stats.playerYSpeed *= stats.drag

    # Enemy logic - Loop through all enemies
    for enemy in stats.enemies:
        ex = ((stats.playerX + stats.mouseX)/2) - enemy['x']
        ey = ((stats.playerY + stats.mouseY)/2) - enemy['y']

        eAngle = math.atan2(ey, ex)
        enemy['vx'] += math.cos(eAngle) * enemy['speed']
        enemy['vy'] += math.sin(eAngle) * enemy['speed']

        enemy['angle'] = math.degrees(math.atan2(ey, ex))
        enemy['x'] += enemy['vx']
        enemy['y'] += enemy['vy']
        enemy['vx'] *= stats.eDrag
        enemy['vy'] *= stats.eDrag

    # Bullet update and collision
    bulletsToKeep = []
    for bullet in stats.bullets:
        bullet['x'] += bullet['vx']
        bullet['y'] += bullet['vy']
        hit = False
        
        # Check collision with each enemy
        for enemy in stats.enemies:
            if logicFunctions.isColiding(stats, bullet['x'], bullet['y'], enemy['x'], enemy['y'], stats.bulletSize + enemy['size'] + 10):
                enemy['hp'] -= stats.bulletDamage
                enemy['vx'] += bullet['vx'] * stats.recoil*1.3
                enemy['vy'] += bullet['vy'] * stats.recoil*1.3
                hit = True
                
                # Enemy death/respawn
                if enemy['hp'] <= 0:
                    stats.enemies.remove(enemy)
                    stats.enemyCount -= 1
                    stats.score += 10
                break # Bullet disappears after hitting one enemy
                
        if not hit and 0 <= bullet['x'] <= 1000 and 0 <= bullet['y'] <= 1000:
            bulletsToKeep.append(bullet)
            
    stats.bullets = bulletsToKeep
    
    screenWraping(stats)
    
    for i in range(len(stats.enemies)):
        for j in range(i + 1, len(stats.enemies)):
            e1 = stats.enemies[i]
            e2 = stats.enemies[j]
            
            if logicFunctions.isColiding(stats, e1['x'], e1['y'], e2['x'], e2['y'], 20):
                # Reverse their directions to bounce
                e1['vx'] *= -1
                e1['vy'] *= -1
                e2['vx'] *= -1
                e2['vy'] *= -1
                
                # Optionally push them slightly apart so they don't get stuck together
                e1['x'] += e1['vx']
                e2['x'] += e2['vx']
    
    # Player vs Enemy collisions
    for enemy in stats.enemies:
            
        if logicFunctions.isColiding(stats, stats.playerX, stats.playerY, enemy['x'], enemy['y'], enemy['size'] + 5):
            stats.playerXSpeed += enemy['vx']
            stats.playerYSpeed += enemy['vy']
            enemy['vx'] -= stats.playerXSpeed*0.75
            enemy['vy'] -= stats.playerYSpeed*0.75
            
            impact = math.hypot(math.hypot(enemy['vx'], stats.playerXSpeed), math.hypot(enemy['vy'], stats.playerYSpeed))/2
            temp = stats.hp - impact
            
            if temp > 0:
                stats.hp -= impact
            else:
                stats.hp = 0.01
    
    if stats.hp <= 0.01:
        stats.hp = 0.01
        stats.gameOverL = 'You lost the game'
        stats.stop()

def trail(app):
    # Player trail
    drawRect(stats.playerX - stats.playerXSpeed * 3-5, stats.playerY - stats.playerYSpeed * 3-5, 10, 10, fill=rgb(255, 0, 0), opacity=5, border=rgb(255, 255, 255), borderWidth=1, rotateAngle=stats.playerAngle)
    drawRect(stats.playerX - stats.playerXSpeed * 2.5-5, stats.playerY - stats.playerYSpeed * 2.5-5, 10, 10, fill=rgb(255, 0, 0), opacity=6, border=rgb(255, 255, 255), borderWidth=1, rotateAngle=stats.playerAngle)
    drawRect(stats.playerX - stats.playerXSpeed * 2-5, stats.playerY - stats.playerYSpeed * 2-5, 10, 10, fill=rgb(255, 0, 0), opacity=7, border=rgb(255, 255, 255), borderWidth=1, rotateAngle=stats.playerAngle)
    drawRect(stats.playerX - stats.playerXSpeed * 1.5-5, stats.playerY - stats.playerYSpeed * 1.5-5, 10, 10, fill=rgb(255, 0, 0), opacity=8, border=rgb(255, 255, 255), borderWidth=1, rotateAngle=stats.playerAngle)
    drawRect(stats.playerX - stats.playerXSpeed * 1-5, stats.playerY - stats.playerYSpeed * 1-5, 10, 10, fill=rgb(255, 0, 0), opacity=9, border=rgb(255, 255, 255), borderWidth=1, rotateAngle=stats.playerAngle)
    drawRect(stats.playerX - stats.playerXSpeed * 0.5-5, stats.playerY - stats.playerYSpeed * 0.5-5, 10, 10, fill=rgb(255, 0, 0), opacity=10, border=rgb(255, 255, 255), borderWidth=1, rotateAngle=stats.playerAngle)

    # Enemy trails
    for enemy in stats.enemies:
        if enemy['type'] == 1:
            i = 0
            j= 3
            n = 5
            while i < 6:
                drawStar(enemy['x'] - enemy['vx'] * j, enemy['y'] - enemy['vy'] * j, enemy['size'] + 5, 3, fill=rgb(255, 255, 0), opacity=n, border=rgb(255, 255, 255), borderWidth=1, roundness=50, rotateAngle=enemy['angle']-90)
                i += 1
                j -= 0.5
                n += 1
        if enemy['type'] == 2:
            i = 0
            j= 3
            n = 5
            while i < 6:
                drawRegularPolygon(enemy['x'] - enemy['vx'] * j, enemy['y'] - enemy['vy'] * j, enemy['size'] + 5, 6, fill=rgb(255, 0, 255), opacity=n, border=rgb(255, 255, 255), borderWidth=1, rotateAngle=enemy['angle']-90)
                i += 1
                j -= 0.5
                n += 1
            
def redrawAll(app):
    drawRect(0, 0, 1000, 1000, fill=rgb(0, 5, 20))
    
    for bullet in stats.bullets:
        drawCircle(bullet['x'], bullet['y'], stats.bulletSize, fill=rgb(0, 200, 200), border=rgb(255, 255, 255), borderWidth=1)
        # Bullet trail
        drawCircle(bullet['x'], bullet['y'], stats.bulletSize + 3, fill=rgb(0, 255, 255), opacity=10)
        drawCircle(bullet['x']-bullet['vx']*0.2, bullet['y']-bullet['vy']*0.2, stats.bulletSize + 2, fill=rgb(0, 255, 255), opacity=8)
        drawCircle(bullet['x']-bullet['vx']*0.4, bullet['y']-bullet['vy']*0.4, stats.bulletSize + 1, fill=rgb(0, 255, 255), opacity=6)
        drawCircle(bullet['x']-bullet['vx']*0.6, bullet['y']-bullet['vy']*0.6, stats.bulletSize, fill=rgb(0, 255, 255), opacity=4)
    
    # Glow trails
    trail(stats)
    drawRect(stats.playerX - stats.playerXSpeed * 0.5-5, stats.playerY - stats.playerYSpeed * 0.5-5, 10, 10, fill=rgb(255, 0, 0), opacity=10, border=rgb(255, 255, 255), borderWidth=1, rotateAngle=stats.playerAngle)
    
    # Player
    drawRect(stats.playerX, stats.playerY, 10, 10, fill=rgb(255, 0, 0), border=rgb(255, 255, 255), borderWidth=1, align='center', rotateAngle=stats.playerAngle)

    # Enemies
    for enemy in stats.enemies:
        if enemy['type'] == 1:
            drawStar(enemy['x'], enemy['y'], enemy['size'] + 5, 3, fill=rgb(255, 255, 0), border=rgb(255, 255, 255), borderWidth=1, roundness=50, rotateAngle=enemy['angle']-90)
            drawRect(enemy['x'], enemy['y'] + 20, enemy['hp']*0.2, 3, fill=rgb(0, 255, 0), align='center')
        if enemy['type'] == 2:
            drawRegularPolygon(enemy['x'], enemy['y'], enemy['size'] + 5, 6, fill=rgb(255, 0, 255), border=rgb(255, 255, 255), borderWidth=1, rotateAngle=enemy['angle']-90)
            drawRect(enemy['x'], enemy['y'] + 20, enemy['hp']*0.2, 3, fill=rgb(0, 255, 0), align='center')

        
    # UI: Health
    drawRect(10, 10, stats.maxHp*2+4, 24, fill=rgb(255, 255, 255))
    drawRect(12, 12, stats.hp*2, 20, fill='lime')
    # UI: Mag
    drawRect(10, 44, stats.maxMag*10+4, 24, fill=stats.magI)
    drawRect(12, 46, stats.mag*10, 20, fill='teal')
    
    # Game over
    if stats.gameOverL:
        drawLabel(stats.gameOverL, 500, 500, size=50, fill=rgb(255, 0, 0), bold=True, border=rgb(255, 255, 255), borderWidth=1)

runApp(width=1000, height=1000)