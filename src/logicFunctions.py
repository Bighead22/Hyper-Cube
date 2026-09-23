import math
import random
import stats
import logicFunctions

def isColiding(app, c1x, c1y, c2x, c2y, hitboxSize):
    if (c2x - hitboxSize <= c1x <= c2x + hitboxSize*2) and (c2y - hitboxSize <= c1y <= c2y + hitboxSize*2):
        return True
    return False