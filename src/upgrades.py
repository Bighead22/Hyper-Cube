from cmu_graphics import *
import random
import stats
import playerStats
import upgrades
import builtins

pyRound = builtins.round  # cmu_graphics overrides round(), so keep Python's own

# Images

upgrades.bulletU = 'images/bullet.png'
upgrades.bulletSpeedU = 'images/bulletSpeed.png'
upgrades.damageOrSizeU = 'images/damageOrSize.png'
upgrades.hpOrRegenU = 'images/hpOrRegen.png'
upgrades.reloadOrMagU = 'images/reloadOrMag.png'
upgrades.speedU = 'images/speed.png'
upgrades.moneyOrLuckU = 'images/moneyOrLuck.png'

# Shop state

upgrades.luck = 1
upgrades.moneyMultiplyer = 1
upgrades.uV = False              # True while the shop is open (game is frozen)
upgrades.currentChoices = []     # 3 rolled cards (a bought card becomes None)
upgrades.message = ''
upgrades.purchases = 0
upgrades.rerollCost = 5


# Rarity

upgrades.rarityNames = ['common', 'uncommon', 'rare', 'epic', 'legendary']
# How much each rarity multiplies every effect on the card
upgrades.rarityPower = {'common': 1, 'uncommon': 1.5, 'rare': 2.25, 'epic': 3.5, 'legendary': 5}
upgrades.rarityCost = {'common': 10, 'uncommon': 20, 'rare': 40, 'epic': 80, 'legendary': 150}
upgrades.rarityColors = {
    'common': (170, 170, 170),
    'uncommon': (60, 220, 60),
    'rare': (60, 120, 255),
    'epic': (180, 60, 255),
    'legendary': (255, 160, 0),
}

def rarity():
    weights = [0.5, 0.3, 0.15*upgrades.luck, 0.04*upgrades.luck*upgrades.luck, 0.01*upgrades.luck*upgrades.luck*upgrades.luck]
    return random.choices(upgrades.rarityNames, weights)[0]

# ----------------------------------------------------------------------------
# CARD DEFINITIONS  -  add as many effects to a card as you want!
#
# Each effect is a dict:
#   'stat'   : name of the variable to change
#   'target' : 'player' (playerStats, default) or 'upgrades'
#   'op'     : 'add' -> stat += value * rarityPower
#              'mul' -> stat *= 1 + value * rarityPower   (negative value = lower)
#   'value'  : the COMMON-rarity amount
#   'int'    : True to round 'add' amounts to whole numbers (min 1)
#   'scale'  : False if rarity should NOT scale this effect (good for downsides)
#   'min'/'max' : optional clamps on the final stat
#   'label'  : text shown on the card
# ----------------------------------------------------------------------------
upgrades.cards = [
    {'name': 'Multishot', 'image': upgrades.bulletU, 'effects': [
        {'stat': 'bulletCount', 'op': 'add', 'value': 1, 'int': True, 'label': 'Bullets per shot'},
        {'stat': 'bulletDamage', 'op': 'mul', 'value': 0.05, 'label': 'Damage'},
    ]},
    {'name': 'Velocity', 'image': upgrades.bulletSpeedU, 'effects': [
        {'stat': 'bulletSpeed', 'op': 'mul', 'value': 0.10, 'label': 'Bullet speed'},
    ]},
    {'name': 'Heavy Rounds', 'image': upgrades.damageOrSizeU, 'effects': [
        {'stat': 'bulletDamage', 'op': 'mul', 'value': 0.15, 'label': 'Damage'},
        {'stat': 'bulletSize', 'op': 'add', 'value': 1, 'int': True, 'label': 'Bullet size'},
    ]},
    {'name': 'Vitality', 'image': upgrades.hpOrRegenU, 'effects': [
        {'stat': 'maxHp', 'op': 'add', 'value': 10, 'int': True, 'label': 'Max HP'},
        {'stat': 'hpRegen', 'op': 'mul', 'value': -0.08, 'min': 150, 'label': 'Regen time'},
    ]},
    {'name': 'Quick Hands', 'image': upgrades.reloadOrMagU, 'effects': [
        {'stat': 'reloadSpeed', 'op': 'mul', 'value': -0.10, 'min': 10, 'label': 'Reload time'},
        {'stat': 'maxMag', 'op': 'add', 'value': 5, 'int': True, 'label': 'Magazine size'},
    ]},
    {'name': 'Thrusters', 'image': upgrades.speedU, 'effects': [
        {'stat': 'accel', 'op': 'mul', 'value': 0.08, 'label': 'Acceleration'},
        {'stat': 'recoilResitance', 'op': 'mul', 'value': -0.08, 'min': 0.02, 'label': 'Recoil'},
    ]},
    {'name': 'Fortune', 'image': upgrades.moneyOrLuckU, 'effects': [
        {'stat': 'moneyMultiplyer', 'target': 'upgrades', 'op': 'add', 'value': 0.10, 'label': 'Coin gain'},
        {'stat': 'luck', 'target': 'upgrades', 'op': 'add', 'value': 0.10, 'label': 'Luck'},
    ]},
]


# Rolling cards

def rollCard(card):
    r = rarity()
    power = upgrades.rarityPower[r]
    effects = []
    lines = []
    for e in card['effects']:
        p = power if e.get('scale', True) else 1
        if e['op'] == 'add':
            amount = e['value'] * p
            if e.get('int'):
                amount = max(1, int(amount + 0.5))
                lines.append(f"+{amount} {e['label']}")
            else:
                amount = pyRound(amount, 2)
                lines.append(f"+{amount} {e['label']}")
        else:
            amount = pyRound(e['value'] * p, 3)
            lines.append(f"{amount*100:+.0f}% {e['label']}")
        effects.append({'stat': e['stat'], 'target': e.get('target', 'player'), 'op': e['op'],
                        'amount': amount, 'min': e.get('min'), 'max': e.get('max')})
    cost = int(upgrades.rarityCost[r] * (1 + 0.1 * upgrades.purchases))
    return {'name': card['name'], 'image': card['image'], 'rarity': r,
            'effects': effects, 'lines': lines, 'cost': cost}

def rollChoices():
    picks = random.sample(upgrades.cards, min(3, len(upgrades.cards)))
    upgrades.currentChoices = [rollCard(c) for c in picks]


# Applying upgrades

def applyEffect(e):
    module = playerStats if e['target'] == 'player' else upgrades
    cur = getattr(module, e['stat'])
    if e['op'] == 'add':
        new = cur + e['amount']
    else:
        new = cur * (1 + e['amount'])
    if e['min'] is not None:
        new = max(e['min'], new)
    if e['max'] is not None:
        new = min(e['max'], new)
    setattr(module, e['stat'], new)

def buy(i):
    choice = upgrades.currentChoices[i]
    if choice is None:
        return
    if stats.coins < choice['cost']:
        upgrades.message = 'Not enough coins!'
        return

    stats.coins -= choice['cost']
    oldMaxHp = playerStats.maxHp
    oldMaxMag = playerStats.maxMag

    for e in choice['effects']:
        applyEffect(e)


    playerStats.recoil = playerStats.bulletSize / 9
    if playerStats.maxHp > oldMaxHp:
        playerStats.hp += playerStats.maxHp - oldMaxHp
    if playerStats.maxMag > oldMaxMag and playerStats.mag != 0.05:
        playerStats.mag += playerStats.maxMag - oldMaxMag

    upgrades.purchases += 1
    rollChoices()  # buying a card rerolls the whole shop
    upgrades.message = f"Bought {choice['rarity']} {choice['name']}!"

def reroll():
    if stats.coins < upgrades.rerollCost:
        upgrades.message = 'Not enough coins to reroll!'
        return
    stats.coins -= upgrades.rerollCost
    upgrades.rerollCost += 5
    rollChoices()
    upgrades.message = 'Rerolled!'


# Shop open

def openShop():
    if not upgrades.currentChoices or all(c is None for c in upgrades.currentChoices):
        rollChoices()
    upgrades.message = ''
    upgrades.uV = True

def closeShop():
    upgrades.uV = False

def cardRect(i):
    w, h = 290, 240
    return 50 + i * 320, 250, w, h

def handleClick(mx, my):
    for i, choice in enumerate(upgrades.currentChoices):
        if choice is None:
            continue
        x, y, w, h = cardRect(i)
        if x - 8 <= mx <= x + w + 8 and y - 8 <= my <= y + h + 157:
            buy(i)
            return