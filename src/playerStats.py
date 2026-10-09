from cmu_graphics import *
import math
import random
import logicFunctions
import enemyStats
import dificultyCurve
import playerStats


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

playerStats.mag = 30
playerStats.maxMag = 30
playerStats.bullets = []
playerStats.recoilResitance = 0.33 # get closer to 0 for less recoil higer number for more
playerStats.bulletSize = 3
playerStats.recoil = playerStats.bulletSize/9
playerStats.bulletCount = 1
playerStats.bulletDamage = 25
playerStats.bulletSpeed = 50
playerStats.reload = 0
playerStats.reloadSpeed = 100
playerStats.reloading = False
playerStats.magI = rgb(255,255,255)