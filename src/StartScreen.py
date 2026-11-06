from cmu_graphics import *
import math

def onAppStart(app):
    app.stepsPerSecond = 60

def onStep(app):
    pass

def redrawAll(app):
    drawRect(0, 0, 1000, 1000, fill=rgb(0, 5, 20))
    #player 1
    drawRect(1000*0.25-125,300,12*10,12*10,fill=rgb(255, 0, 0), rotateAngle=0, opacity=100,border=rgb(255, 255, 255), borderWidth=1*10,align='center')
    drawRegularPolygon(1000*0.25-125,300,4*10,4,fill=rgb(255, 255, 255), rotateAngle=45, opacity=100,border=rgb(255, 255, 255), borderWidth=1*10)
    #player 2
    drawRegularPolygon(1000*0.5-125,300,6*math.sqrt(2)*10,6,fill=rgb(0, 255, 0), rotateAngle=0, opacity=100,border=rgb(255, 255, 255), borderWidth=1*10)
    drawRegularPolygon(1000*0.5-125,300,5*10,6,fill=rgb(255, 255, 255), rotateAngle=0, opacity=100,border=rgb(255, 255, 255), borderWidth=1*10)
    #player 3
    drawRegularPolygon(1000*0.75-125,300,7*math.sqrt(2)*10,3,fill=rgb(0, 0, 255), rotateAngle=33, opacity=100,border=rgb(255, 255, 255), borderWidth=1*10)
    drawRegularPolygon(1000*0.75-125,300,5*10,3,fill=rgb(255, 255, 255), rotateAngle=33, opacity=100,border=rgb(255, 255, 255), borderWidth=1*10)
    #player 4
    drawCircle(1000*1-125,300,7*10,fill=rgb(255, 150, 0), opacity=100,border=rgb(255, 255, 255), borderWidth=1*10)
    drawCircle(1000*1-125,300,4.5*10,fill=rgb(255, 255, 255), opacity=100,border=rgb(255, 255, 255), borderWidth=1*10)
    
    # borders
    drawRect(1000*0.25-125,300,23*10,23*10,fill=None, rotateAngle=0, opacity=100,border=rgb(255, 255, 255), borderWidth=1*10,align='center')
    drawRect(1000*0.5-125,300,23*10,23*10,fill=None, rotateAngle=0, opacity=100,border=rgb(255, 255, 255), borderWidth=1*10,align='center')
    drawRect(1000*0.75-125,300,23*10,23*10,fill=None, rotateAngle=0, opacity=100,border=rgb(255, 255, 255), borderWidth=1*10,align='center')
    drawRect(1000*1-125,300,23*10,23*10,fill=None, rotateAngle=0, opacity=100,border=rgb(255, 255, 255), borderWidth=1*10,align='center')
    
    #labels 
    drawLabel('Cube', 1000*0.25-125, 450, size=20, fill=rgb(255, 255, 255), align='center')
    drawLabel('Green', 1000*0.5-125, 450, size=20, fill=rgb(255, 255, 255), align='center')
    drawLabel('Prism', 1000*0.75-125, 450, size=20, fill=rgb(255, 255, 255), align='center')
    drawLabel('Orbit', 1000*1-125, 450, size=20, fill=rgb(255, 255, 255), align='center')

runApp(width=1000, height=1000)