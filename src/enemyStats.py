from cmu_graphics import *
import math
import random
import logicFunctions
import enemyStats
import dificultyCurve
import playerStats

enemyStats.enemyspawnCD = (10)*30 # lower number for faster spawn higher number for slower spawn chang number in ()
enemyStats.enemyCountCD = 1
enemyStats.enemyCount = 1 # Change this to add more enemies
enemyStats.eDrag = 0.99
enemyStats.enemyType = 1
enemyStats.enemyHpMultiplier = 1

enemyStats.enemies = []
    # Spawn the enemies based on the initial enemy count
for i in range(enemyStats.enemyCount):
    enemyStats.enemies.append({'x': random.randint(0, 1000) * (i + 1),'y': 1000,'hp': random.randint(100, 200) * enemyStats.enemyHpMultiplier,'vx': 0,'vy': 0,'angle': 0,'size': 10, 'type' : random.randint(1,2), 'speed' : 0.75})