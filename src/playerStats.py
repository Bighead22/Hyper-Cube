from cmu_graphics import *
import math
import random
import stats
import logicFunctions
import logicFunctions
import enemyStats
import playerStats
import dificultyCurve

playerStats.playerAngle = 0
playerStats.playerX = 375
playerStats.playerY = 375
playerStats.playerXSpeed = 0
playerStats.playerYSpeed = 0
playerStats.accel = 0.5
playerStats.drag = 0.99

playerStats.maxHp = 100
playerStats.hp = 100
playerStats.hpRegen = 1500 # lower number for faster regen higher number for slower regen

playerStats.mag = 12
playerStats.maxMag = 12
playerStats.bullets = []
playerStats.recoilResitance = 1 # get closer to 0 for less recoil higer number for more
playerStats.bulletSize = 3
playerStats.recoil = playerStats.bulletSize/9
playerStats.bulletCount = 1
playerStats.bulletDamage = 25
playerStats.bulletSpeed = 20
playerStats.reload = 0
playerStats.reloadSpeed = 100
playerStats.reloading = False
playerStats.magI = rgb(255,255,255)