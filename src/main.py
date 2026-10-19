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
import upgrades

app.setMaxShapeCount(160000)

def onAppStart(app):

    app.stepsPerSecond = 60

def onMousePress(app, mouseX, mouseY):
    if upgrades.uV:
        upgrades.handleClick(mouseX, mouseY)
        return
    if stats.gameOverL:
        return
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
    if stats.gameOverL:
        return
    if key == 's':
        if upgrades.uV:
            upgrades.closeShop()
        else:
            upgrades.openShop()
    elif key == 'e' and upgrades.uV:
        upgrades.reroll()
    elif key == 'r' and not upgrades.uV:
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
    if upgrades.uV or stats.gameOverL:
        return
    stats.score += 1/app.stepsPerSecond
    stats.time += 1/app.stepsPerSecond
    enemyStats.enemyHpMultiplier = dificultyCurve.difficulty(stats.time+43)/20
    
    while len(enemyStats.enemies) < enemyStats.enemyCount:
        enemyStats.spawnEnemy(playerStats.playerX, playerStats.playerY, enemyStats.enemyHpMultiplier)

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
        cfg = enemyStats.types[enemy['type']]

        # Newly spawned enemies just fade in and sit still
        if enemy['spawn'] > 0:
            enemy['spawn'] -= 1
            continue

        ex = playerStats.playerX - enemy['x']
        ey = playerStats.playerY - enemy['y']
        eAngle = math.atan2(ey, ex)
        enemy['angle'] = math.degrees(eAngle)

        # Only steer toward the player when not stunned from a recent hit
        if enemy['stun'] > 0:
            enemy['stun'] -= 1
        else:
            enemy['vx'] += math.cos(eAngle) * cfg['accel']
            enemy['vy'] += math.sin(eAngle) * cfg['accel']

        # Soft speed cap (knockback can briefly exceed it, then eases back down)
        spd = math.hypot(enemy['vx'], enemy['vy'])
        if spd > cfg['maxSpeed']:
            f = max(cfg['maxSpeed'] / spd, 0.85)
            enemy['vx'] *= f
            enemy['vy'] *= f

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
                enemy['vx'] += bullet['vx'] * 0.2
                enemy['vy'] += bullet['vy'] * 0.2
                hit = True
                
                # Enemy death/respawn
                if enemy['hp'] <= 0:
                    enemyStats.enemies.remove(enemy)
                    enemyStats.enemyCount -= 1
                    stats.score += 10
                    if enemy['type'] == 1:
                        stats.coins += 5 * upgrades.moneyMultiplyer
                    if enemy['type'] == 2:
                        stats.coins += 7.5 * upgrades.moneyMultiplyer
                break # Bullet disappears after hitting one enemy
                
        if not hit and 0 <= bullet['x'] <= 1000 and 0 <= bullet['y'] <= 1000:
            bulletsToKeep.append(bullet)
            
    playerStats.bullets = bulletsToKeep
    
    screenWraping(stats)
    
    # Enemy vs enemy: gently push apart so they spread out instead of stacking
    for i in range(len(enemyStats.enemies)):
        for j in range(i + 1, len(enemyStats.enemies)):
            e1 = enemyStats.enemies[i]
            e2 = enemyStats.enemies[j]
            if e1['spawn'] > 0 or e2['spawn'] > 0:
                continue
            dx = e2['x'] - e1['x']
            dy = e2['y'] - e1['y']
            d = math.hypot(dx, dy)
            minD = e1['size'] + e2['size'] + 10
            if d < minD:
                if d == 0:
                    dx, dy, d = random.random() - 0.5, random.random() - 0.5, 1
                push = (minD - d) / 2
                nx, ny = dx / d, dy / d
                e1['x'] -= nx * push
                e1['y'] -= ny * push
                e2['x'] += nx * push
                e2['y'] += ny * push

    # Player vs Enemy: fixed damage per hit, then brief invulnerability + knockback
    if enemyStats.playerInvuln > 0:
        enemyStats.playerInvuln -= 1

    for enemy in enemyStats.enemies:
        if enemy['spawn'] > 0:
            continue
        if logicFunctions.isColiding(app, playerStats.playerX, playerStats.playerY, enemy['x'], enemy['y'], enemy['size'] + 5):
            if enemyStats.playerInvuln > 0:
                continue
            cfg = enemyStats.types[enemy['type']]
            dx = playerStats.playerX - enemy['x']
            dy = playerStats.playerY - enemy['y']
            d = math.hypot(dx, dy) or 1
            nx, ny = dx / d, dy / d

            playerStats.hp = max(0.01, playerStats.hp - playerStats.maxHp * cfg['damage'])
            enemyStats.playerInvuln = enemyStats.playerIFrames

            # Shove both apart; enemy pauses its chase briefly
            playerStats.playerXSpeed += nx * enemyStats.knockback
            playerStats.playerYSpeed += ny * enemyStats.knockback
            enemy['vx'] = -nx * enemyStats.knockback
            enemy['vy'] = -ny * enemyStats.knockback
            enemy['stun'] = enemyStats.hitStun

    if playerStats.hp <= 0.01:
        playerStats.hp = 0.01
        stats.gameOverL = 'You lost the game'

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
        if enemy['spawn'] > 0:
            continue
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
            
def drawShop(app):
    if not upgrades.uV:
        return
    drawRect(0, 0, 1000, 1000, fill='black', opacity=65)
    drawLabel('UPGRADES', 500, 110, size=40, fill='white', bold=True)
    drawLabel(f'Coins: {int(stats.coins)}', 500, 155, size=22, fill=rgb(255, 220, 0), bold=True)
    drawLabel(f'Click a card to buy   |   E: reroll ({upgrades.rerollCost} coins)   |   S: close', 500, 190, size=18, fill='white')
    for i, choice in enumerate(upgrades.currentChoices):
        if choice is None:
            continue
        x, y, w, h = upgrades.cardRect(i)
        color = rgb(*upgrades.rarityColors[choice['rarity']])
        drawRect(x - 8, y - 8, w + 16, h + 165, fill=rgb(15, 15, 30), border=color, borderWidth=4)
        drawImage(choice['image'], x, y, width=w, height=h)
        drawLabel(choice['rarity'].upper(), x + w/2, y + h + 20, size=16, fill=color, bold=True)
        drawLabel(choice['name'], x + w/2, y + h + 46, size=22, fill='white', bold=True)
        for j, line in enumerate(choice['lines']):
            drawLabel(line, x + w/2, y + h + 72 + j*20, size=16, fill=rgb(200, 255, 200))
        afford = stats.coins >= choice['cost']
        drawLabel(f"Cost: {choice['cost']}", x + w/2, y + h + 145, size=18, bold=True,
                  fill=rgb(0, 255, 0) if afford else rgb(255, 80, 80))
    if upgrades.message:
        drawLabel(upgrades.message, 500, 740, size=24, fill='white', bold=True)

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
    drawRect(playerStats.playerX, playerStats.playerY, 10, 10, fill=rgb(255, 0, 0), border=rgb(255, 255, 255), borderWidth=1, align='center', rotateAngle=playerStats.playerAngle, opacity=(35 if enemyStats.playerInvuln % 8 < 4 and enemyStats.playerInvuln > 0 else 100))

    # Enemies
    for enemy in enemyStats.enemies:
        eo = 30 if enemy['spawn'] > 0 else 100   # faded while spawning in
        if enemy['type'] == 1:
            drawStar(enemy['x'], enemy['y'], enemy['size'] + 5, 3, fill=rgb(255, 255, 0), border=rgb(255, 255, 255), borderWidth=1, roundness=50, rotateAngle=enemy['angle']-90, opacity=eo)
            drawRect(enemy['x'], enemy['y'] + 20, (enemy['hp'])*(0.2/enemyStats.enemyHpMultiplier), 3, fill=rgb(0, 255, 0), align='center')
        if enemy['type'] == 2:
            drawRegularPolygon(enemy['x'], enemy['y'], enemy['size'] + 5, 6, fill=rgb(255, 0, 255), border=rgb(255, 255, 255), borderWidth=1, rotateAngle=enemy['angle']-90, opacity=eo)
            drawRect(enemy['x'], enemy['y'] + 20, (enemy['hp'])*(0.2/enemyStats.enemyHpMultiplier), 3, fill=rgb(0, 255, 0), align='center')

    # UI: Health
    drawRect(10, 10, playerStats.maxHp*2+4, 24, fill=rgb(255, 255, 255))
    drawRect(12, 12, playerStats.hp*2, 20, fill='lime')
    # UI: Mag
    drawRect(10, 44, playerStats.maxMag*5+4, 24, fill=playerStats.magI)
    drawRect(12, 46, playerStats.mag*5, 20, fill='teal')
    #UI:
    #Money
    drawLabel(int(stats.coins), 10,980, size=20,fill = rgb(255,255,255))
    
    drawLabel('S: upgrades', 990, 980, size=16, fill=rgb(255,255,255), align='right')
    drawShop(app)

    # Game over
    if stats.gameOverL:
        drawLabel(stats.gameOverL, 500, 500, size=50, fill=rgb(255, 0, 0), bold=True, border=rgb(255, 255, 255), borderWidth=1)

runApp(width=1000, height=1000)