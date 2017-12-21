#!/usr/bin/python
import cherrypy
from cherrypy.process.plugins import Monitor
from saplugin import SAEnginePlugin
from satool import SATool
from lunchdb import *
from sqlalchemy import cast, Date
from datetime import datetime, date, time, timedelta
import random
import os

#Configuration options
DBFILE = "lunch.db"
NOREPEAT_DAYS = 21
TIME_DAYS  = [3]         #Day(s) of week to run votes (Monday is 0, see datetime.date.weekday())
TIME_START = time(9,00)  #Time each day to open the vote
#TIME_END   = time(11,30) #Time each day to close the vote
TIME_END = time(23,59)

def doRank(query):
    # query = db.query(Restaurant).all()

    maxvotes  = float(max([I.votes for I in query]))
    maxvisits = float(max([I.visits for I in query]))
    
    ranks = {}
    for I in query:
        if I.visits == 0:
            ranks[I] = -100.0 * (I.votes / maxvotes)
        else:
            ranks[I] = 100.0 * (float(I.visits) / I.votes)
            if ranks[I] == 100:
                ranks[I] += 10*I.visits

    #Return array of tuples (Restaurant, Rank) reverse-sorted by rank
    return sorted([(K,ranks[K]) for K in ranks], key=lambda I:I[1], reverse=True)

class Manager(Monitor):
    ''' 
    This plugin manages creation and operation of vote sessions.
    Is is set up to be run once a minute, and operates based on the 
    current time and day
    '''
    def __init__(self, bus, interval):
        super(Manager, self).__init__(bus, self.run, interval)
        self.event = None
    
    def start(self):
        self.bus.subscribe("get-event", self.getEvent)
        super(Manager, self).start()

    def stop(self):
        self.bus.unsubscribe("get-event", self.getEvent)
        super(Manager, self).stop()

    def getEvent(self):
        return self.event

    def run(self):              
        db = self.bus.publish("bind-session")[0]
        D, T = self.now()                
        if self.event is None:
            if D in TIME_DAYS and T >= TIME_START and T < TIME_END:
                #Start a new vote                
                self.startVote(db)
        else:
            if T >= TIME_END:
                #End the current vote
                self.endVote(db)     
        self.bus.publish("commit-session")

    def now(self):
        #Returns the day of the week and the current time
        now = datetime.today()
        return now.weekday(), time(now.hour, now.minute)

    def today(self):
        #Returns the date (with time zeroed out)
        now = datetime.today()
        return date(now.year, now.month, now.day)

    def startVote(self, db):
        self.bus.log("*** Starting a new vote!")
        choices = self.getChoices(db)
        event = Event(choice1=choices[0].id, 
            choice2=choices[1].id, 
            choice3=choices[2].id, 
            choice4=choices[3].id, 
            choice5=choices[4].id)
        db.add(event)
        db.commit()
        self.event = event.id

    def endVote(self, db):
        self.bus.log("*** Voting has closed!")        
        #TODO: tabulate responses!
        self.event = None

    def getChoices(self, db):
        '''
            Chooses a restaurant list by:
            1) sorting by rank
            2) dividing the list into "thirds"
            3) selecting one from each third
            4) randomly selecting from the list up to self.choices            
        '''
        votedate = self.today()
        restaurants = db.query(Restaurant).all()

        #Select restaurants out of the noRepeatWeeks range            
        validRestaurants = [R for R in restaurants if R.last <= votedate - timedelta(1+NOREPEAT_DAYS)]
        #ranked = sorted(validRestaurants, key=lambda I:I.rank, reverse=True)
        ranked = validRestaurants

        #Divide into "thirds"
        third = len(ranked)/3
        choices = [random.choice(ranked[:third]),
                   random.choice(ranked[third:-third]),
                   random.choice(ranked[-third:])]
        ranked = [R for R in ranked if R not in choices]
        choices.extend(random.sample(ranked, 5-3))
        random.shuffle(choices)
        return choices


class Lunch(object):
    def header(self, title="Lunch", subtitle=""):
        title = "%s%s"%(title, (": " + subtitle) if subtitle else "")
        head = '''<html><head>
        <title>%s</title>
        <link rel="stylesheet" href="static/style.css"/>
        </head>'''%title   
        head += "<body><div id=header>%s</div>"%(title)        
        return head

    def footer(self):
        foot = '</body></html>'
        return foot

    @cherrypy.expose
    def index(self):
        db = cherrypy.request.db
        datelimit = datetime.today() - timedelta(NOREPEAT_DAYS)        

        # site = "<html><head><title>Lunch</title></head>"
        site = self.header("Lunch")

        '''
        site += 'Restaurants available for vote (before %s):<br/>'%datetime.strftime(datelimit, "%Y-%m-%d")
        site += '<table >'
        site += '<tr><td>Restaurant</td><td>Votes</td><td>Visits</td><td>Last Visit</td><td>Rank</td></tr>'
        query = db.query(Restaurant).order_by(Restaurant.visits.desc())
        query = query.filter(Restaurant.last < datetime.strftime(datelimit, "%Y-%m-%d"))
        for row in query.all():  
            rank = 1
            if row.votes > 0:
                rank = float(row.visits) / float(row.votes)

            site += '<tr>'
            site += '<td>%s</td>'%(row.name)
            site += '<td>%d</td>'%(row.votes)
            site += '<td>%d</td>'%(row.visits)
            site += '<td>%s</td>'%(row.last)
            site += '<td>%f</td>'%(rank)
            site += '</tr>'
        site += '</table>'
        '''

        site += '<h2>Restaurant Leaderboard</h2><br/>'
        site += '<table >'
        site += '<tr><th>Rank</th><th>Restaurant</th><th>Votes</th><th>Visits</th><th>Last Visit</th></tr>'
        query = db.query(Restaurant).order_by(Restaurant.visits.desc())        
        i = 1
        for row in query.all():
            rank = 1
            if row.votes > 0:
                rank = float(row.visits) / float(row.votes)

            site += '<tr>'
            site += '<td>%d</td>'%(i)
            site += '<td>%s</td>'%(row.name)
            site += '<td>%d</td>'%(row.votes)
            site += '<td>%d</td>'%(row.visits)
            site += '<td>%s</td>'%(row.last)            
            site += '</tr>'
            i+=1
        site += '</table>'

        eventcount = db.query(Event).count()
        site += "<h3>Voting events: %d</h3>"%eventcount
        votecount = db.query(Vote).count()
        site += "<h3>Total votes cast: %d</h3>"%votecount        

        # site += "</body></html>"
        site += self.footer()
        return site

    @cherrypy.expose
    def vote(self, u="", action="", **args):
        db = cherrypy.request.db
        eventid = cherrypy.engine.publish("get-event")[0]

        site = self.header("Lunch", "Vote") 

        #TODO: Verify the user is in the Persons table and check if they've voted in this event already        
        person = db.query(Person).filter_by(email=u).one_or_none()
        if person is None:
            site += "You aren't allowed to vote"            
        else:
            site += "<h2>Hello, %s</h2>"%(person.name)
            vote = db.query(Vote).filter_by(event=eventid).filter_by(user=person.id).one_or_none()

            if eventid is None:
                site += "Voting is closed!"
            else:
                event = db.query(Event).filter_by(id=eventid).one()
                choices = event.getChoices()

                if action=='vote':
                    # SUBMITTING A VOTE
                    if vote is None:
                        site += "<h2>Vote received!</h2>"
                    else:
                        site += "<h2>Updated vote received!</h2>"
                    
                    site += '<table >'                
                    i = 1
                    for c in choices:                
                        restaurant = db.query(Restaurant).filter_by(id=c).one()
                        site += '''<tr>                
                            <td>%s</td>
                            <td>%s</td>                        
                        </tr>'''%(restaurant.name,args['c%d'%i])
                        i += 1 
                    site += '</table>'

                else:
                    if vote is not None:
                        site += "<h3>You have already voted</h3>"
                    # ALLOW USER TO VOTE
                    site += '<form method="post" action="vote">'
                    site += '<input type="hidden" name="u", value="%s">'%u
                    site += '<table >'
                    site += '<tr><th/><th>#1</th><th>#2</th><th>#3</th><th>#4</th><th>#5</th><th>No</th>'
                    i = 1
                    for c in choices:                
                        restaurant = db.query(Restaurant).filter_by(id=c).one()
                        site += '''<tr>                
                            <td>%s</td>
                            <td><input type="radio" name="c%d" value="1"></td>
                            <td><input type="radio" name="c%d" value="2"></td>
                            <td><input type="radio" name="c%d" value="3"></td>
                            <td><input type="radio" name="c%d" value="4"></td>
                            <td><input type="radio" name="c%d" value="5"></td>
                            <td><input type="radio" name="c%d" value="6" checked></td>
                        </tr>'''%(restaurant.name,i,i,i,i,i,i)
                        i += 1 
                    site += '</table>'
                    site += '<button type="submit" name="action" value="vote">Vote</button>'
                    site += '</form>'

        site += self.footer()
        return site

    @cherrypy.expose
    def admin(self, action="", name="", visits=0, date="", email="", **kwargs):
        db = cherrypy.request.db
        
        site = self.header("Lunch", "Admin") 

        cherrypy.log("ADMIN ACTION: %s"%action)

        if action == 'increment_visit':
            row = db.query(Restaurant).filter(Restaurant.name==name).one()
            row.visits += 1
            dt = datetime.today()
            row.last = datetime(dt.year, dt.month, dt.day)
        elif action == 'decrement_visit':
            row = db.query(Restaurant).filter(Restaurant.name==name).one()
            row.visits -= 1            
        elif action == 'increment_vote':
            row = db.query(Restaurant).filter(Restaurant.name==name).one()
            row.votes += 1      
        elif action == 'decrement_vote':
            row = db.query(Restaurant).filter(Restaurant.name==name).one()
            row.votes -= 1                 
        elif action == 'add_restaurant':
            rows = db.query(Restaurant).filter(Restaurant.name==name).all()
            if len(rows) == 0:
                if not date:
                    date = "1900-01-01"
                date = datetime.strptime(date,"%Y-%m-%d")
                print "ADD", name, visits, date
                R = Restaurant(name=name, visits=visits, lastvisit=date, votes=0)
                db.add(R)
            else:
                site += "Restaurant \"%s\" already in database!<br/>"%name
        elif action == 'del_restaurant':
            for row in db.query(Restaurant).filter(Restaurant.name==name).all():
                db.delete(row)
        elif action == 'add_person':
            P = Person(name=name, email=email)
            db.add(P)
        elif action == 'del_person':
            for row in db.query(Person).filter(Person.name==name).all():         
                db.delete(row)

        site += '<hr/>Restaurants in the list:<br/>'
        site += '<table>'
        site += '<tr><th/><th>Rank</th><th>Restaurant</th><th>Votes</th><th>Visits</th><th>Last Visit</th><th>Added</th></tr>'
        Q = db.query(Restaurant).order_by(Restaurant.visits.desc())
        R = doRank(Q)
        for row, rank in R:
            site += '''<tr>
                <td>                    
                    <form style="float:right" method="post" action="admin">
                        <input type="hidden" name="name" value="%s">
                        <button type="submit" name="action" value="del_restaurant">X</button>
                    </form>
                </td>'''%(row.name)
            site += '<td>%d</td>'%(rank)
            site += '<td>%s</td>'%(row.name)
            site += '''<td>%d
                    <form style="float:right" method="post" action="admin">
                        <input type="hidden" name="name" value="%s">
                        <button type="submit" name="action" value="increment_vote">+</button>
                        <button type="submit" name="action" value="decrement_vote">-</button>
                    </form></td>'''%(row.votes, row.name)
            site += '''<td>%s
                    <form style="float:right" method="post" action="admin">
                        <input type="hidden" name="name" value="%s">
                        <button type="submit" name="action" value="increment_visit">+</button>
                        <button type="submit" name="action" value="decrement_visit">-</button>
                    </form>
                    </td>'''%(row.visits, row.name)
            site += '<td>%s</td>'%(row.last)
            site += '<td>%s</td>'%(row.added)
            site += '</tr>'
        site += '</table>'
        site += '</br>'
        site += '''<form method="post", action="admin">
            Name<input type="text" name="name">
            Visits<input type="number" name="visits" min="0" value=0>
            Last Visit<input type="date" name="date">
            <button class=button type="submit" name="action" value="add_restaurant">Add Restaurant</button>
            </form>'''      

        site += '<hr/>People:<br/>'
        site += '<table>'
        site += '<tr><th/><th>Name</td><th>Email</th></tr>'
        Q = db.query(Person).order_by(Person.name)
        for row in Q:
            site += '''<tr>
                <td>                    
                    <form style="float:right" method="post" action="admin">
                        <input type="hidden" name="name" value="%s">
                        <button type="submit" name="action" value="del_person">X</button>
                    </form>
                </td>'''%(row.name)
            site += '<td>%s</td>'%(row.name)
            site += '<td>%s</td>'%(row.email)    
            site += '</tr>'
        site += '</table>'
        site += '</br>'
        site += '''<form method="post", action="admin">
            Name<input type="text" name="name" required>
            Email<input type="email" name="email">            
            <button type="submit" name="action" value="add_person">Add Person</button>
            </form>'''  

        site += self.footer()
        return site

def foo(*args):
    print args
    return 1

if __name__ == '__main__':
    conf = {
        '/': {
            'tools.db.on': True
        },
        '/static': {
            'tools.staticdir.on': True,
            'tools.staticdir.dir': os.path.join(os.getcwd(), "static")
        }
    }

    #init the DB
    LunchDB(DBFILE) 

    Manager(cherrypy.engine, 1).subscribe()
    SAEnginePlugin(cherrypy.engine, 'sqlite:///'+DBFILE).subscribe()
    cherrypy.tools.db = SATool()
    cherrypy.quickstart(Lunch(), '/', conf)