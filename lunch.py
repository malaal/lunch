#!/usr/bin/python
import cherrypy
from cherrypy.process.plugins import Monitor
from saplugin import SAEnginePlugin
from satool import SATool
from lunchdb import LunchDB, Restaurant, Event, Vote
from sqlalchemy import cast, Date
from datetime import datetime, date, time, timedelta

DBFILE = "lunch.db"
NOREPEAT_DAYS = 21
TIME_DAYS  = [3]         #Day(s) of week to run votes (Monday is 0, see datetime.date.weekday())
TIME_START = time(9,00)  #Time each day to open the vote
TIME_END   = time(11,30) #Time each day to close the vote

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
        self.bus.unsubscribe("get-event")
        super(Manager, self).stop()

    def getEvent(self):
        return self.event

    def run(self):              
        db = self.bus.publish("bind-session")[0]
        D, T = self.now()                
        if self.event is None:
            if D in TIME_DAYS and T >= TIME_START:
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
        self.event = Event(option1=choices[0], 
            option2=choices[1], 
            option3=choices[2], 
            option4=choices[3], 
            option5=choices[4])
        db.add(self.event)

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
        ranked = sorted(validRestaurants, key=lambda I:I.rank, reverse=True)

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
    @cherrypy.expose
    def index(self):
        db = cherrypy.request.db
        datelimit = datetime.today() - timedelta(NOREPEAT_DAYS)        

        site = "<html><head><title>Lunch</title></head>"
        site += "<body><h1>Lunch</h1>"

        '''
        site += 'Restaurants available for vote (before %s):<br/>'%datetime.strftime(datelimit, "%Y-%m-%d")
        site += '<table border=1>'
        site += '<tr><td>Restaurant</td><td>Votes</td><td>Visits</td><td>Last Visit</td><td>Rank</td></tr>'
        query = db.query(Restaurant).order_by(Restaurant.visits.desc())
        query = query.filter(Restaurant.lastvisit < datetime.strftime(datelimit, "%Y-%m-%d"))
        for row in query.all():  
            rank = 1
            if row.votes > 0:
                rank = float(row.visits) / float(row.votes)

            site += '<tr>'
            site += '<td>%s</td>'%(row.name)
            site += '<td>%d</td>'%(row.votes)
            site += '<td>%d</td>'%(row.visits)
            site += '<td>%s</td>'%(row.lastvisit)
            site += '<td>%f</td>'%(rank)
            site += '</tr>'
        site += '</table>'
        '''

        site += '<h2>Restaurant Leaderboard</h2><br/>'
        site += '<table border=1>'
        site += '<tr><td>Rank</td><td>Restaurant</td><td>Votes</td><td>Visits</td><td>Last Visit</td></tr>'
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
            site += '<td>%s</td>'%(row.lastvisit)            
            site += '</tr>'
            i+=1
        site += '</table>'

        eventcount = db.query(Event).count()
        site += "<h3>Voting events: %d</h3>"%eventcount
        votecount = db.query(Vote).count()
        site += "<h3>Total votes cast: %d</h3>"%votecount        

        site += "</body></html>"
        return site

    @cherrypy.expose
    def admin(self, action="", name="", visits=0, date="", **kwargs):
        db = cherrypy.request.db
        
        site = "<html><head><title>Lunch Admin</title></head>"
        site += "<body><h1>Lunch Admin</h1>"

        cherrypy.log("ADMIN ACTION: %s"%action)

        if action == 'increment':
            row = db.query(Restaurant).filter(Restaurant.name==name).one()
            row.visits += 1
            dt = datetime.today()
            row.lastvisit = datetime(dt.year, dt.month, dt.day)
        elif action == 'decrement':
            row = db.query(Restaurant).filter(Restaurant.name==name).one()
            row.visits -= 1            
        elif action == 'increment_vote':
            row = db.query(Restaurant).filter(Restaurant.name==name).one()
            row.votes += 1      
        elif action == 'decrement_vote':
            row = db.query(Restaurant).filter(Restaurant.name==name).one()
            row.votes -= 1                 
        elif action == 'delete':
            for row in db.query(Restaurant).filter(Restaurant.name==name).all():
                db.delete(row)
        elif action == 'add':
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


        site += 'Restaurants in the list:<br/>'
        site += '<table border=1 width=80%>'
        site += '<tr><td/><td>Rank</td><td>Restaurant</td><td>Votes</td><td>Visits</td><td>Last Visit</td></tr>'
        Q = db.query(Restaurant).order_by(Restaurant.visits.desc())
        R = doRank(Q)
        for row, rank in R:
            site += '''<tr>
                <td>                    
                    <form style="float:right" method="post" action="admin">
                        <input type="hidden" name="name" value="%s">
                        <button type="submit" name="action" value="delete">X</button>
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
                        <button type="submit" name="action" value="increment">+</button>
                        <button type="submit" name="action" value="decrement">-</button>
                    </form>
                    </td>'''%(row.visits, row.name)
            site += '<td>%s</td>'%(row.lastvisit)
            site += '</tr>'
        site += '</table>'
        site += '</br>'
        site += '''<form method="post", action="admin">
            Name<input type="text" name="name">
            Visits<input type="number" name="visits" min="0", value=0>
            Last Visit<input type="date" name="date">
            <button type="submit" name="action" value="add">Add Restaurant</button>
            </form>'''      

        site += "</body></html>"
        return site

def foo(*args):
    print args
    return 1

if __name__ == '__main__':
    conf = {
        '/': {
            'tools.db.on': True
        }
    }

    #init the DB
    LunchDB(DBFILE) 

    Manager(cherrypy.engine, 1).subscribe()
    SAEnginePlugin(cherrypy.engine, 'sqlite:///'+DBFILE).subscribe()
    cherrypy.tools.db = SATool()
    cherrypy.quickstart(Lunch(), '/', conf)