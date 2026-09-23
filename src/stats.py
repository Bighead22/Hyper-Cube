from cmu_graphics import *
import math
import random
import stats
import upgrades

stats.stepsPerSecond = 60
stats.score = 0

stats.mouseX = 375
stats.mouseY = 375

stats.playerAngle = 0
stats.playerX = 375
stats.playerY = 375
stats.playerXSpeed = 0
stats.playerYSpeed = 0
stats.accel = 0.5
stats.drag = 0.99

stats.maxHp = 100
stats.hp = 100
stats.hpRegen = 1500 # lower number for faster regen higher number for slower regen

stats.mag = 12
stats.maxMag = 12
stats.bullets = []
stats.recoilResitance = 1 # get closer to 0 for less recoil higer number for more
stats.bulletSize = 3
stats.recoil = stats.bulletSize/9
stats.bulletCount = 1
stats.bulletDamage = 25
stats.bulletSpeed = 20
stats.reload = 0
stats.reloadSpeed = 100
stats.reloading = False
stats.magI = rgb(255,255,255)

# Enemy Setup
stats.enemyspawnCD = (10)*30 # lower number for faster spawn higher number for slower spawn chang number in ()
stats.enemyCountCD = 1
stats.enemyCount = 1 # Change this to add more enemies
stats.eDrag = 0.99
stats.enemyType = 1
stats.enemyHpMultiplier = 1

stats.enemies = []
    # Spawn the enemies based on the initial enemy count
for i in range(stats.enemyCount):
    stats.enemies.append({'x': 100 * (i + 1),'y': 100,'hp': random.randint(100, 200) * stats.enemyHpMultiplier,'vx': 0,'vy': 0,'angle': 0,'size': 10, 'type' : random.randint(1,2), 'speed' : 0.75})
    
stats.gameOverL = ''

def isColiding(app, c1x, c1y, c2x, c2y, hitboxSize):
    if (c2x - hitboxSize <= c1x <= c2x + hitboxSize*2) and (c2y - hitboxSize <= c1y <= c2y + hitboxSize*2):
        return True
    return False