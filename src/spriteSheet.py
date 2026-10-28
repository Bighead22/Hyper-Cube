from cmu_graphics import *

app.testX1 = 500
app.testY1 = 500

def onAppStart(app):
    app.stepsPerSecond = 60

def onStep(app):
    pass

def player1(x,y,s,r,o):
    drawImage("images/players/player1.png", x, y, width=10*s, height=7.5*s, rotateAngle=r,align='center',opacity=o)
    pass

def redrawAll(app):
    drawRect(0, 0, 1000, 1000, fill=rgb(0, 5, 20))
    player1(app.testX1,app.testY1,5,0,100)

runApp(width=1000, height=1000)