from cmu_graphics import *
import math
import random
import enemyStats

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
    1: {'size': 15, 'accel': 0.5, 'maxSpeed': 7.5, 'damage': 0.25},
    2: {'size': 5,  'accel': 0.5, 'maxSpeed': 12, 'damage': 0.15},
    3: {'size': 20,  'accel': 0.5, 'maxSpeed': 3, 'damage': 0.75},
}

enemyStats.enemies = []

def spawnEnemy(playerX, playerY, hpMultiplier):
    etype = random.randint(1, 3)
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
def bossTexture(x, y, r, o):
    drawRegularPolygon(x,y,50,8,fill=rgb(255, 0, 255), rotateAngle=r, opacity=o,border=rgb(255, 255, 255), borderWidth=1)
    drawRegularPolygon(x,y,40,8,fill=rgb(235, 0, 235), rotateAngle=r, opacity=o)
    drawRegularPolygon(x,y,30,8,fill=rgb(215, 0, 215), rotateAngle=r, opacity=o)

# ---------- Boss settings (tweak these!) ----------
enemyStats.bossInterval = 90        # seconds between boss spawns
enemyStats.nextBossTime = 60        # game time (seconds) of the next boss
enemyStats.boss = None              # the live boss (None when there isn't one)
enemyStats.bossOrbs = []            # orbs currently flying around
enemyStats.bossSize = 50
enemyStats.bossBaseHp = 10000        # multiplied by enemyHpMultiplier (never below 1x)
enemyStats.bossSpawnGrace = 120     # frames the boss is a harmless ghost (warning)
enemyStats.bossAccel = 0.12         # how fast the boss drifts toward you
enemyStats.bossMaxSpeed = 2.5
enemyStats.bossContactDamage = 0  # fraction of player max HP on touch
enemyStats.bossAttackCD = 120       # frames between orb rings (lower = faster)
enemyStats.bossOrbCount = 16        # orbs per ring
enemyStats.bossOrbSpeed = 4
enemyStats.bossOrbSize = 8
enemyStats.bossOrbDamage = 0.33     # fraction of player max HP per orb hit
enemyStats.bossOrbLife = 400        # frames before an orb disappears
enemyStats.bossCoins = 100          # coin reward (times moneyMultiplyer)

def spawnBoss(playerX, playerY, hpMultiplier):
    x, y = 500, 500
    for _ in range(30):
        x = random.randint(100, 900)
        y = random.randint(100, 900)
        if math.hypot(x - playerX, y - playerY) >= 400:
            break
    hp = enemyStats.bossBaseHp * max(1, hpMultiplier)
    enemyStats.boss = {
        'x': x, 'y': y, 'vx': 0, 'vy': 0,
        'hp': hp, 'maxHp': hp,
        'size': enemyStats.bossSize,
        'rot': 0,
        'spawn': enemyStats.bossSpawnGrace,
        'cd': enemyStats.bossAttackCD,
        'ringOffset': 0,
    }

def fireOrbRing(boss):
    # Radial attack: a ring of orbs shooting out in all directions.
    # Below 50% HP the boss gets angrier: more orbs per ring.
    n = enemyStats.bossOrbCount
    if boss['hp'] < boss['maxHp'] / 2:
        n = int(n * 1.5)
    for i in range(n):
        a = boss['ringOffset'] + i * 2 * math.pi / n
        enemyStats.bossOrbs.append({
            'x': boss['x'], 'y': boss['y'],
            'vx': math.cos(a) * enemyStats.bossOrbSpeed,
            'vy': math.sin(a) * enemyStats.bossOrbSpeed,
            'life': enemyStats.bossOrbLife,
        })
    # Shift the next ring by half a gap so the safe spots keep changing
    boss['ringOffset'] += math.pi / n

def drawOrb(x, y, r):
    drawCircle(x, y, r + 5, fill=rgb(255, 0, 255), opacity=25)
    drawCircle(x, y, r, fill=rgb(255, 80, 255), border=rgb(255, 255, 255), borderWidth=1)
    drawCircle(x, y, r / 2, fill=rgb(255, 255, 255))