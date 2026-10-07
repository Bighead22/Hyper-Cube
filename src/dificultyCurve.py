from cmu_graphics import *
import math
import random
import logicFunctions
import enemyStats
import dificultyCurve
import stats

#(10sin(0.2x)+2x)-25

def difficulty(time):
    return ((10*math.sin((0.2*time))) + 2*time)-25