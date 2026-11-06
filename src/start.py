from cmu_graphics import *
import math
import os
import stats
#pyton src//start.py


def onAppStart(app):
    
    app.playerA = 'jkegwebg'
    
    app.stepsPerSecond = 60
    app.selectedPlayer = 1
    app.player1 = True
    app.player2 = True
    app.player3 = True
    app.player4 = True
    app.screen0 = True
    app.screen1 = False
    
def onKeyPress(app, key):
    if key == 'escape':
        app.screen0 = True
        app.screen1 = False
        app.player1 = True
        app.player2 = True
        app.player3 = True
        app.player4 = True
    
def onMousePress(app, mx, my):
    if app.screen0:
        app.player1 = False
        app.player2 = False
        app.player3 = False
        app.player4 = False
        app.screen0 = False
        app.screen1 = True
        if mx > 10 and mx < 240:
            app.player1 = True
            app.selectedPlayer = 1
        elif mx > 260 and mx < 490:
            app.player2 = True
            app.selectedPlayer = 2
        elif mx > 510 and mx < 740:
            app.player3 = True
            app.selectedPlayer = 3
        elif mx > 760 and mx < 990:
            app.player4 = True
            app.selectedPlayer = 4
        app.screen0 = False
    if app.screen1:
        if mx > 500 and mx < 600 and my > 700 and my < 800:
            os.system("python src\\main.py")
            pass
        
    
def onStep(app):
    stats.setPlayerType("src\\playerSelection.txt", app.selectedPlayer)
    if app.selectedPlayer == 1:
        app.playerA = 'The Cube has a high single shot bullet and a dash ability that is activated by "W A S D"'
    elif app.selectedPlayer == 2:
        app.playerA = 'Green has a machine Gun, it is very hard to kill and when you press "Space" you telport to the Mouse'
    elif app.selectedPlayer == 3:
        app.playerA = 'Prism is a Glass Cannon that shoots lasers when you press "Space" all beams converge into a big one'
    elif app.selectedPlayer == 4:
        app.playerA = 'Orbit Shoots balls that orbits around it will also crash the game if there are too many'

def redrawAll(app):
    drawRect(0, 0, 1000, 1000, fill=rgb(0, 5, 20))
    #player 1
    drawRect(1000*0.25-125,300,12*10,12*10,fill=rgb(255, 0, 0), rotateAngle=0, opacity=100,border=rgb(255, 255, 255), borderWidth=1*10,align='center',visible = app.player1)
    drawRegularPolygon(1000*0.25-125,300,4*10,4,fill=rgb(255, 255, 255), rotateAngle=45, opacity=100,border=rgb(255, 255, 255), borderWidth=1*10,visible = app.player1)
    #player 2
    drawRegularPolygon(1000*0.5-125,300,6*math.sqrt(2)*10,6,fill=rgb(0, 255, 0), rotateAngle=0, opacity=100,border=rgb(255, 255, 255), borderWidth=1*10,visible = app.player2)
    drawRegularPolygon(1000*0.5-125,300,5*10,6,fill=rgb(255, 255, 255), rotateAngle=0, opacity=100,border=rgb(255, 255, 255), borderWidth=1*10,visible = app.player2)
    #player 3
    drawRegularPolygon(1000*0.75-125,300,7*math.sqrt(2)*10,3,fill=rgb(0, 0, 255), rotateAngle=33, opacity=100,border=rgb(255, 255, 255), borderWidth=1*10,visible = app.player3)
    drawRegularPolygon(1000*0.75-125,300,5*10,3,fill=rgb(255, 255, 255), rotateAngle=33, opacity=100,border=rgb(255, 255, 255), borderWidth=1*10,visible = app.player3)
    #player 4
    drawCircle(1000*1-125,300,7*10,fill=rgb(255, 150, 0), opacity=100,border=rgb(255, 255, 255), borderWidth=1*10,visible = app.player4)
    drawCircle(1000*1-125,300,4.5*10,fill=rgb(255, 255, 255), opacity=100,border=rgb(255, 255, 255), borderWidth=1*10,visible = app.player4)
    
    # borders
    drawRect(1000*0.25-125,300,23*10,23*10,fill=None, rotateAngle=0, opacity=100,border=rgb(255, 255, 255), borderWidth=1*10,align='center',visible = app.player1)
    drawRect(1000*0.5-125,300,23*10,23*10,fill=None, rotateAngle=0, opacity=100,border=rgb(255, 255, 255), borderWidth=1*10,align='center',visible = app.player2)
    drawRect(1000*0.75-125,300,23*10,23*10,fill=None, rotateAngle=0, opacity=100,border=rgb(255, 255, 255), borderWidth=1*10,align='center',visible = app.player3)
    drawRect(1000*1-125,300,23*10,23*10,fill=None, rotateAngle=0, opacity=100,border=rgb(255, 255, 255), borderWidth=1*10,align='center',visible = app.player4)
    
    #labels 
    drawLabel('The Cube', 1000*0.25-125, 450, size=50, fill=rgb(255, 255, 255), align='center',visible = app.screen0)
    drawLabel('Green', 1000*0.5-125, 450, size=50, fill=rgb(255, 255, 255), align='center',visible = app.screen0)
    drawLabel('Prism', 1000*0.75-125, 450, size=50, fill=rgb(255, 255, 255), align='center',visible = app.screen0)
    drawLabel('Orbit', 1000*1-125, 450, size=50, fill=rgb(255, 255, 255), align='center',visible = app.screen0)
    
    drawRect(500, 750, 200, 100, fill=rgb(0, 255, 0), align='center', visible = not app.screen0,border=rgb(255, 255, 255), borderWidth=1*10)
    drawLabel('Start', 500, 750, size=50, fill=rgb(255, 255, 255), align='center',visible = not app.screen0)
    drawLabel('Select a player Press ESC to go Back', 500, 750, size=50, fill=rgb(255, 255, 255), align='center',visible = app.screen0)
    
    drawLabel(app.playerA, 500, 450, size=20, fill=rgb(255, 255, 255), align='center',visible = app.screen1)

runApp(width=1000, height=1000)