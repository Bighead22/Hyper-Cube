from cmu_graphics import *
import enemyStats
import playerStats
import enemyStats

def onAppStart(app):
    app.stepsPerSecond = 60

def onStep(app):
    pass

def redrawAll(app):
    drawRect(0, 0, 1000, 1000, fill=rgb(0, 5, 20))
    playerStats.player1(100,100,0,100)
    playerStats.player2(200,100,0,100)
    playerStats.player3(300,100,0,100)
    playerStats.player4(400,100,0,100)
    enemyStats.bossTexture(500,100,0,100)
    drawRect(300, 900-12, 404, 22, fill=rgb(255, 255, 255))
    drawRect(302, 900-10, 400 * max(0, 3000) / 3000, 18, fill=rgb(255, 0, 255))
    drawLabel('BOSS', 500, 900-54, size=16, fill='white', bold=True)

runApp(width=1000, height=1000)