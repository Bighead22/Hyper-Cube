from cmu_graphics import *
import playerStats

def onAppStart(app):
    app.stepsPerSecond = 60

def onStep(app):
    pass

def redrawAll(app):
    drawRect(0, 0, 1000, 1000, fill=rgb(0, 5, 20))
    playerStats.player1(100,100,0,100)
    playerStats.player2(200,100,0,100)
    playerStats.player3(300,100,0,100)
    

runApp(width=1000, height=1000)