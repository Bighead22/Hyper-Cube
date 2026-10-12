from cmu_graphics import *
import math
import random
import stats
import logicFunctions
import logicFunctions
import enemyStats
import playerStats
import dificultyCurve
import upgrades

upgrades.bulletU = 'images/bullet.png'
upgrades.bulletSpeedU = 'images/bulletSpeed.png'
upgrades.damageOrSizeU = 'images/damageOrSize.png'
upgrades.hpOrRegenU = 'images/hpOrRegen.png'
upgrades.reloadOrMagU = 'images/reloadOrMag.png'
upgrades.speedU = 'images/speed.png'
upgrades.moneyOrLuckU = 'images/moneyOrLuck.png'
upgrades.luck = 1
upgrades.moneyMultiplyer = 1

def rarity():
    rarities = ['common', 'uncommon', 'rare', 'epic', 'legendary']
    weights = [0.5, 0.3, 0.15*upgrades.luck, 0.04*upgrades.luck*upgrades.luck, 0.01*upgrades.luck*upgrades.luck*upgrades.luck]
    return random.choices(rarities, weights)[0]