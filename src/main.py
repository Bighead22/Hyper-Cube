#python src/main.py
#pip install cmu-graphics
#ollama pull qwen3.5:4b
#ollama run qwen3.5:4b  

from cmu_graphics import *
import math
import random
import stats
import logicFunctions
import enemyStats
import playerStats
import dificultyCurve

app.setMaxShapeCount(160000)

def onAppStart(app):

    app.stepsPerSecond = 60

def onMousePress(app, mouseX, mouseY):
    if playerStats.mag != 0.05:
        dx = mouseX - playerStats.playerX
        dy = mouseY - playerStats.playerY
        baseAngle = math.atan2(dy, dx)
        
        spreadAngle = math.radians(5*playerStats.bulletCount)
        
        if playerStats.bulletCount > 1:
            angleStep = spreadAngle / (playerStats.bulletCount - 1)
            startAngle = baseAngle - (spreadAngle / 2)
        else:
            angleStep = 0
            startAngle = baseAngle

        for i in range(playerStats.bulletCount):
            angle = startAngle + (i * angleStep)
            vx = math.cos(angle) * playerStats.bulletSpeed
            vy = math.sin(angle) * playerStats.bulletSpeed
            playerStats.bullets.append({'x': playerStats.playerX, 'y': playerStats.playerY, 'vx': vx, 'vy': vy})
            playerStats.playerXSpeed -= (vx * playerStats.recoil) * playerStats.recoilResitance
            playerStats.playerYSpeed -= (vy * playerStats.recoil) * playerStats.recoilResitance
            i += 1

    if playerStats.mag > 1:
        playerStats.mag-=1
    if playerStats.mag == 1:
        playerStats.mag = 0.05

def onKeyPress(app, key):
    if key == 'r':
        playerStats.reloading = True
    
def onMouseMove(app, mouseX, mouseY):
    stats.mouseX = mouseX
    stats.mouseY = mouseY

def screenWraping(app):
    # Player wrapping
    if playerStats.playerX < 0: playerStats.playerX = 1000
    if playerStats.playerX > 1000: playerStats.playerX = 0
    if playerStats.playerY < 0: playerStats.playerY = 1000
    if playerStats.playerY > 1000: playerStats.playerY = 0

    # Enemy wrapping
    for enemy in enemyStats.enemies:
        if enemy['x'] < 0: enemy['x'] = 1000
        if enemy['x'] > 1000: enemy['x'] = 0
        if enemy['y'] < 0: enemy['y'] = 1000
        if enemy['y'] > 1000: enemy['y'] = 0
    
def onStep(app):
    stats.score += 1/app.stepsPerSecond
    stats.time += 1/app.stepsPerSecond
    enemyStats.enemyHpMultiplier = dificultyCurve.difficulty(stats.time+43)/20
    enemyStats.speedMultiplier = dificultyCurve.difficulty(stats.time+43)/20
    print(dificultyCurve.difficulty(stats.time+43))
    while len(enemyStats.enemies) < enemyStats.enemyCount:
        enemyStats.enemies.append({'x': random.randint(0, 1000),'y': 1000,'hp': random.randint(100, 200)*enemyStats.enemyHpMultiplier,'vx': 0,'vy': 0,'angle': 0,'size': 10, 'type' : random.randint(1,2), 'speed' : 0.75*enemyStats.speedMultiplier})
    for enemy in enemyStats.enemies:
        if enemy['type'] == 1:
            enemy['size'] = 15
            enemy['speed'] = 0.75
        if enemy['type'] == 2:
            enemy['size'] = 5
            enemy['speed'] = 1.25

    if dificultyCurve.difficulty(stats.time+43) > (enemyStats.maxEnemyCount*2):
        enemyStats.enemyCount += 2
        enemyStats.maxEnemyCount += 2
    
    playerStats.hp += playerStats.maxHp/playerStats.hpRegen
    if playerStats.hp > playerStats.maxHp:
        playerStats.hp = playerStats.maxHp

    if playerStats.reloading:
        playerStats.magI = None
        playerStats.reload += 1
        if playerStats.reload % 2 == 0:
            playerStats.magI = rgb(255,255,255)
        if playerStats.reload >= playerStats.reloadSpeed:
            playerStats.mag = playerStats.maxMag
            playerStats.reloading = False
            playerStats.reload = 0
            playerStats.magI = rgb(255,255,255)

    dx = stats.mouseX - playerStats.playerX
    dy = stats.mouseY - playerStats.playerY
    dist = math.hypot(dx, dy)
        
    if dist > 5:
        angle = math.atan2(dy, dx)
        playerStats.playerXSpeed += math.cos(angle) * playerStats.accel
        playerStats.playerYSpeed += math.sin(angle) * playerStats.accel
    
    playerStats.playerAngle = math.degrees(math.atan2(dy, dx))
    playerStats.playerX += playerStats.playerXSpeed
    playerStats.playerY += playerStats.playerYSpeed
    playerStats.playerXSpeed *= playerStats.drag
    playerStats.playerYSpeed *= playerStats.drag

    # Enemy logic - Loop through all enemies
    for enemy in enemyStats.enemies:
        ex = (playerStats.playerX) - enemy['x']
        ey = (playerStats.playerY) - enemy['y']

        eAngle = math.atan2(ey, ex)
        enemy['vx'] += math.cos(eAngle) * enemy['speed']
        enemy['vy'] += math.sin(eAngle) * enemy['speed']

        enemy['angle'] = math.degrees(math.atan2(ey, ex))
        enemy['x'] += enemy['vx']
        enemy['y'] += enemy['vy']
        enemy['vx'] *= enemyStats.eDrag
        enemy['vy'] *= enemyStats.eDrag

    # Bullet update and collision
    bulletsToKeep = []
    for bullet in playerStats.bullets:
        bullet['x'] += bullet['vx']
        bullet['y'] += bullet['vy']
        hit = False
        
        # Check collision with each enemy
        for enemy in enemyStats.enemies:
            if logicFunctions.isColiding(app, bullet['x'], bullet['y'], enemy['x'], enemy['y'], playerStats.bulletSize + enemy['size'] + 10):
                enemy['hp'] -= playerStats.bulletDamage
                enemy['vx'] += bullet['vx'] * playerStats.recoil*1.3
                enemy['vy'] += bullet['vy'] * playerStats.recoil*1.3
                hit = True
                
                # Enemy death/respawn
                if enemy['hp'] <= 0:
                    enemyStats.enemies.remove(enemy)
                    enemyStats.enemyCount -= 1
                    stats.score += 10
                    if enemy['type'] == 1:
                        stats.coins += 3
                    if enemy['type'] == 2:
                        stats.coins += 5
                break # Bullet disappears after hitting one enemy
                
        if not hit and 0 <= bullet['x'] <= 1000 and 0 <= bullet['y'] <= 1000:
            bulletsToKeep.append(bullet)
            
    playerStats.bullets = bulletsToKeep
    
    screenWraping(stats)
    
    for i in range(len(enemyStats.enemies)):
        for j in range(i + 1, len(enemyStats.enemies)):
            e1 = enemyStats.enemies[i]
            e2 = enemyStats.enemies[j]
            
            if logicFunctions.isColiding(app, e1['x'], e1['y'], e2['x'], e2['y'], 20):
                # Reverse their directions to bounce
                e1['vx'] *= -1
                e1['vy'] *= -1
                e2['vx'] *= -1
                e2['vy'] *= -1
                
                # Optionally push them slightly apart so they don't get stuck together
                e1['x'] += e1['vx']
                e2['x'] += e2['vx']
    
    # Player vs Enemy collisions
    for enemy in enemyStats.enemies:
            
        if logicFunctions.isColiding(app, playerStats.playerX, playerStats.playerY, enemy['x'], enemy['y'], enemy['size'] + 5):
            playerStats.playerXSpeed += enemy['vx']
            playerStats.playerYSpeed += enemy['vy']
            enemy['vx'] -= playerStats.playerXSpeed*0.75
            enemy['vy'] -= playerStats.playerYSpeed*0.75
            
            impact = math.hypot(math.hypot(enemy['vx'], playerStats.playerXSpeed), math.hypot(enemy['vy'], playerStats.playerYSpeed))/2
            temp = playerStats.hp - impact
            
            if temp > 0:
                playerStats.hp -= impact
            else:
                playerStats.hp = 0.01
    
    if playerStats.hp <= 0.01:
        playerStats.hp = 0.01
        stats.gameOverL = 'You lost the game'
        app.stepsPerSecond = 0.0000001

def trail(app):
    # Player trail
    drawRect(playerStats.playerX - playerStats.playerXSpeed * 3-5, playerStats.playerY - playerStats.playerYSpeed * 3-5, 10, 10, fill=rgb(255, 0, 0), opacity=5, border=rgb(255, 255, 255), borderWidth=1, rotateAngle=playerStats.playerAngle)
    drawRect(playerStats.playerX - playerStats.playerXSpeed * 2.5-5, playerStats.playerY - playerStats.playerYSpeed * 2.5-5, 10, 10, fill=rgb(255, 0, 0), opacity=6, border=rgb(255, 255, 255), borderWidth=1, rotateAngle=playerStats.playerAngle)
    drawRect(playerStats.playerX - playerStats.playerXSpeed * 2-5, playerStats.playerY - playerStats.playerYSpeed * 2-5, 10, 10, fill=rgb(255, 0, 0), opacity=7, border=rgb(255, 255, 255), borderWidth=1, rotateAngle=playerStats.playerAngle)
    drawRect(playerStats.playerX - playerStats.playerXSpeed * 1.5-5, playerStats.playerY - playerStats.playerYSpeed * 1.5-5, 10, 10, fill=rgb(255, 0, 0), opacity=8, border=rgb(255, 255, 255), borderWidth=1, rotateAngle=playerStats.playerAngle)
    drawRect(playerStats.playerX - playerStats.playerXSpeed * 1-5, playerStats.playerY - playerStats.playerYSpeed * 1-5, 10, 10, fill=rgb(255, 0, 0), opacity=9, border=rgb(255, 255, 255), borderWidth=1, rotateAngle=playerStats.playerAngle)
    drawRect(playerStats.playerX - playerStats.playerXSpeed * 0.5-5, playerStats.playerY - playerStats.playerYSpeed * 0.5-5, 10, 10, fill=rgb(255, 0, 0), opacity=10, border=rgb(255, 255, 255), borderWidth=1, rotateAngle=playerStats.playerAngle)

    # Enemy trails
    for enemy in enemyStats.enemies:
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
    
    for bullet in playerStats.bullets:
        drawCircle(bullet['x'], bullet['y'], playerStats.bulletSize, fill=rgb(0, 200, 200), border=rgb(255, 255, 255), borderWidth=1)
        # Bullet trail
        drawCircle(bullet['x'], bullet['y'], playerStats.bulletSize + 3, fill=rgb(0, 255, 255), opacity=10)
        drawCircle(bullet['x']-bullet['vx']*0.2, bullet['y']-bullet['vy']*0.2, playerStats.bulletSize + 2, fill=rgb(0, 255, 255), opacity=8)
        drawCircle(bullet['x']-bullet['vx']*0.4, bullet['y']-bullet['vy']*0.4, playerStats.bulletSize + 1, fill=rgb(0, 255, 255), opacity=6)
        drawCircle(bullet['x']-bullet['vx']*0.6, bullet['y']-bullet['vy']*0.6, playerStats.bulletSize, fill=rgb(0, 255, 255), opacity=4)
    
    # Glow trails
    trail(playerStats)
    drawRect(playerStats.playerX - playerStats.playerXSpeed * 0.5-5, playerStats.playerY - playerStats.playerYSpeed * 0.5-5, 10, 10, fill=rgb(255, 0, 0), opacity=10, border=rgb(255, 255, 255), borderWidth=1, rotateAngle=playerStats.playerAngle)
    
    # Player
    drawRect(playerStats.playerX, playerStats.playerY, 10, 10, fill=rgb(255, 0, 0), border=rgb(255, 255, 255), borderWidth=1, align='center', rotateAngle=playerStats.playerAngle)

    # Enemies
    for enemy in enemyStats.enemies:
        if enemy['type'] == 1:
            drawStar(enemy['x'], enemy['y'], enemy['size'] + 5, 3, fill=rgb(255, 255, 0), border=rgb(255, 255, 255), borderWidth=1, roundness=50, rotateAngle=enemy['angle']-90)
            drawRect(enemy['x'], enemy['y'] + 20, enemy['hp']*0.2, 3, fill=rgb(0, 255, 0), align='center')
        if enemy['type'] == 2:
            drawRegularPolygon(enemy['x'], enemy['y'], enemy['size'] + 5, 6, fill=rgb(255, 0, 255), border=rgb(255, 255, 255), borderWidth=1, rotateAngle=enemy['angle']-90)
            drawRect(enemy['x'], enemy['y'] + 20, enemy['hp']*0.2, 3, fill=rgb(0, 255, 0), align='center')

        
    # UI: Health
    drawRect(10, 10, playerStats.maxHp*2+4, 24, fill=rgb(255, 255, 255))
    drawRect(12, 12, playerStats.hp*2, 20, fill='lime')
    # UI: Mag
    drawRect(10, 44, playerStats.maxMag*5+4, 24, fill=playerStats.magI)
    drawRect(12, 46, playerStats.mag*5, 20, fill='teal')
    #UI:
    #Money
    drawLabel(stats.coins, 10,980, size=20,fill = rgb(255,255,255))
    
    # Game over
    if stats.gameOverL:
        drawLabel(stats.gameOverL, 500, 500, size=50, fill=rgb(255, 0, 0), bold=True, border=rgb(255, 255, 255), borderWidth=1)

runApp(width=1000, height=1000)