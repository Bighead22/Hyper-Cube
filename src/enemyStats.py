from cmu_graphics import *
import math
import random
import logicFunctions
import enemyStats
import dificultyCurve
import playerStats

enemyStats.enemyspawnCD = (10)*30 # lower number for faster spawn higher number for slower spawn chang number in ()
enemyStats.enemyCount = -2 # Change this to add more enemies
enemyStats.maxEnemyCount = 0
enemyStats.eDrag = 0.95          # was 0.99 (0.99 let enemies build up huge, unavoidable speed)
enemyStats.enemyType = 1
enemyStats.enemyHpMultiplier = 1
enemyStats.speedMultiplier = 1
enemyStats.readyToSpawn = True

# ---------- Fairness settings (tweak these!) ----------
enemyStats.minSpawnDist = 300    # enemies never spawn closer than this to the player
enemyStats.spawnGrace = 60       # frames an enemy is a harmless "ghost" after spawning (60 = 1 sec)
enemyStats.hitStun = 25          # frames an enemy stops chasing after it hits the player
enemyStats.playerIFrames = 40    # frames the player can't be hurt after taking a hit
enemyStats.knockback = 5         # how hard a hit shoves the player / enemy apart
enemyStats.playerInvuln = 0      # (runtime counter, leave at 0)

# Per-type stats. damage is a fraction of the player's max HP per hit.
# accel = how fast it steers toward you, maxSpeed = soft speed cap.
enemyStats.types = {
    1: {'size': 15, 'accel': 0.5, 'maxSpeed': 15, 'damage': 0.25},
    2: {'size': 5,  'accel': 1, 'maxSpeed': 30, 'damage': 0.15},
}

enemyStats.enemies = []

def spawnEnemy(playerX, playerY, hpMultiplier):
    etype = random.randint(1, 2)
    cfg = enemyStats.types[etype]
    x, y = 0, 0
    # Pick a random spot that is far enough away from the player
    for _ in range(30):
        x = random.randint(0, 1000)
        y = random.randint(0, 1000)
        if math.hypot(x - playerX, y - playerY) >= enemyStats.minSpawnDist:
            break
    enemyStats.enemies.append({
        'x': x, 'y': y,
        'hp': random.randint(100, 200) * hpMultiplier,
        'vx': 0, 'vy': 0, 'angle': 0,
        'size': cfg['size'], 'type': etype, 'speed': cfg['accel'],
        'spawn': enemyStats.spawnGrace,   # spawn-in timer (harmless while > 0)
        'stun': 0,                        # post-hit timer (doesn't chase while > 0)
    })