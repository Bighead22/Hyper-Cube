from cmu_graphics import *
import math
import random
import stats

stats.stepsPerSecond = 60
stats.score = 0
stats.coins = 0
stats.time = 0
stats.mouseX = 375
stats.mouseY = 375
stats.gameOverL = ''

def isColiding(app, c1x, c1y, c2x, c2y, hitboxSize):
    if (c2x - hitboxSize <= c1x <= c2x + hitboxSize*2) and (c2y - hitboxSize <= c1y <= c2y + hitboxSize*2):
        return True
    return False

#((10sin(0.2x)+2x)-25)x/500
def difficulty(time):
    return (((10*math.sin((0.3*time))) + 2*time)-25)*time/750

def getPlayerType(filename):
    with open(filename, "r") as file:
        content = file.read().split()
        if content:
            return float(content[-1])  # Use int(content[-1]) if only whole numbers
    return None

def setPlayerType(filename, playerType):
    with open(filename, "w") as file:
        file.write(str(playerType))