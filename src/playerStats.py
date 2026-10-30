from cmu_graphics import *
import playerStats
import math


playerStats.playerType = 2

#p1 Specific
playerStats.dashsize = 10
#p2 Specific
playerStats.fireRate = 1
#p3 Specific

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
playerStats.recoilResitance = 0.01 # get closer to 0 for less recoil higer number for more
playerStats.bulletSize = 3
playerStats.recoil = playerStats.bulletSize/9
playerStats.bulletCount = 1
playerStats.bulletDamage = 25
playerStats.bulletSpeed = 50
playerStats.reload = 0
playerStats.reloadSpeed = 100
playerStats.reloading = False
playerStats.magI = rgb(255,255,255)

def player1(x,y,r,o):
    drawRect(x,y,12,12,fill=rgb(255, 0, 0), rotateAngle=r, opacity=o,border=rgb(255, 255, 255), borderWidth=1,align='center')
    drawRegularPolygon(x,y,4,4,fill=rgb(255, 255, 255), rotateAngle=r+45, opacity=o,border=rgb(255, 255, 255), borderWidth=1)
def player2(x,y,r,o):
    drawRegularPolygon(x,y,6*math.sqrt(2),6,fill=rgb(0, 255, 0), rotateAngle=r, opacity=o,border=rgb(255, 255, 255), borderWidth=1)
    drawRegularPolygon(x,y,5,6,fill=rgb(255, 255, 255), rotateAngle=r, opacity=o,border=rgb(255, 255, 255), borderWidth=1)
def player3(x,y,r,o):
    drawRegularPolygon(x,y,7*math.sqrt(2),3,fill=rgb(0, 0, 255), rotateAngle=r+33, opacity=o,border=rgb(255, 255, 255), borderWidth=1)
    drawRegularPolygon(x,y,5,3,fill=rgb(255, 255, 255), rotateAngle=r+33, opacity=o,border=rgb(255, 255, 255), borderWidth=1)
def dashing1(key):
    if key == 'a':
        playerStats.playerXSpeed -= playerStats.dashsize
    if key == 'd':
        playerStats.playerXSpeed += playerStats.dashsize
    if key == 'w':
        playerStats.playerYSpeed -= playerStats.dashsize
    if key == 's':
        playerStats.playerYSpeed += playerStats.dashsize
