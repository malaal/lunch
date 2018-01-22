#!/usr/bin/python
from LunchDB import *
from LunchConfig import LunchConfig
from LunchMail import LunchMail

import cherrypy
from cherrypy.process.plugins import Monitor
from saplugin import SAEnginePlugin
from satool import SATool

from sqlalchemy import cast, Date

from pyvotecore.schulze_method import SchulzeMethod

from datetime import datetime, date, time, timedelta
import random
import os
from copy import copy
from collections import Counter

# Load global configuration options
cfg = LunchConfig("lunchconfig.json")

def dirichlet_mean(arr):
    """
    Computes the Dirichlet mean with a prior.
    Adapted from: http://blog.districtdatalabs.com/computing-a-bayesian-estimate-of-star-rating-means
    Returns a ranking from 0-5
    """
    PRIOR = [2,0,0,0,0,0]

    counter   = Counter(arr)
    votes     = [counter.get(n, 0) for n in range(1, 6)]
    posterior = map(sum, zip(votes, PRIOR))
    N         = sum(posterior)
    weights   = map(lambda i: (i[0])*i[1], enumerate(posterior))

    return float(sum(weights)) / N

def calculateRank(db, user=None, update=False):
    '''Returns a dict of {'rest name':rank} for the entire vote set,
    OR: input a user object to calculate that user's personal ranking
    update = TRUE to update the rank entry in a restaurant's db entry'''

    rankings = {}
    for rest in db.query(Restaurant).all():
        ranks = db.query(Vote.rank).join(Choice).join(Restaurant).filter(Restaurant.name==rest.name)
        if user is not None:
            ranks = ranks.filter(Vote.user==user.id)
        ranks = [r[0] for r in ranks.all()] #db returns single results in a tuple for some reason
        
        rank = dirichlet_mean(ranks)
        rankings[rest.name] = rank
        if update:
            rest.rank = rank

    if update:
        db.commit()

    return rankings   

class Manager(Monitor):
    ''' 
    This CherryPy plugin manages creation and operation of vote sessions.
    Is is set up to be run once a minute, and operates based on the 
    current time and day, and LunchConfig
    '''
    def __init__(self, bus, interval):
        super(Manager, self).__init__(bus, self.run, interval)
        self.eventid = None

        #init the DB
        LunchDB(cfg.dbfile)     

        #init the mailer
        self.mail = LunchMail(cfg.smtp["server"], cfg.smtp["port"], cfg.smtp["user"], cfg.smtp["pass"])

    def start(self):
        self.bus.subscribe("get-event", self.getEvent)
        self.bus.subscribe("calculate", self.calculate)
        super(Manager, self).start()

    def stop(self):
        self.bus.unsubscribe("get-event", self.getEvent)
        self.bus.unsubscribe("calculate", self.calculate)
        super(Manager, self).stop()

    def getEventId(self):
        return self.eventid

    def getEvent(self):
        if self.eventid is not None:
            db = self.bus.publish("bind-session")[0]
            return db.query(Event).filter_by(id=self.eventid).one_or_none()        
        else:
            return None

    def run(self):              
        db = self.bus.publish("bind-session")[0]
        D, T = self.now()                
        if self.eventid is None:
            if D in cfg.time_days and T >= cfg.time_start and T < cfg.time_end:
                #Start a new vote                
                self.startVote(db)
        else:
            if T >= cfg.time_end:
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
        event = Event()
        event.choices = [Choice(num=i, restaurant=choices[i].id) for i in range(5)]            
        db.add(event)
        db.commit()
        self.eventid = event.id

        for user in db.query(User).all():
            link = "http://%s/vote?u=%s"%(cfg.hostname, user.email)

            email = '''
            <html><body>
            <h1>Lunch!</h1>
            <p>The lunch ballot is now open for %s.
            <a style="font-weight: bold;" href="%s">Vote Here!</a>
            </p>
            <p><b>Voting will be open until %s today.</b></p>
            <p>If you can't make it to lunch this week, ignore this email for now.</p>
            <p>Today's options are:
                <ul>
            '''%(event.date, link, cfg.time_end.strftime("%H:%M"))
            for c in event.choices:
                email += "<li>%s</li>"%(db.query(Restaurant).join(Choice).filter(Choice.id==c.id).one().name)
            email +='''
                </ul>
            </p>
            </body></html>
            '''

            self.bus.log("Emailing %s"%user.email)
            self.mail.sendhtml([user.email], "Lunch Vote Open %s"%event.date, email)

    def endVote(self, db):
        self.bus.log("*** Voting has closed!")
        event = self.getEvent()
        winner, tb_user = self.calculate(db)   
    
        if winner is None:
            self.bus.log("Received no votes!")
        else:
            #Increment the restaurant's win list and visited date
            rest = db.query(Restaurant).filter(Restaurant.name==winner).one_or_none()        
            rest.visits += 1
            rest.last = datetime.today()
            db.commit()

            #Recalculate the restaurant ranking
            calculateRank(db, update=True)

            #Email the users who voted only
            attendees = db.query(User).join(Vote).filter(Vote.event==event.id).all()
            email = '''
            <html><body>
            <h1>Lunch today: %s</h1>
            <p>The lunch ballot is closed for %s.</p>
            <p>Who is coming today:
                <ul>
            '''%(winner, event.date)
            for user in attendees:
                email += "<li>%s</li>"%(user.name)
            email +='''
                </ul>
            </p>
            <p>This week's tie-breaker was: %s</p>
            </body></html>
            '''%(tb_user)

            self.bus.log("Emailing Results")
            self.mail.sendhtml([user.email for user in attendees], "Lunch Vote Closed %s"%event.date, email)

        self.eventid = None

    def getChoices(self, db):
        '''
            Chooses a restaurant list for an event by:
            1) sort by rank 
            2) dividing the list into "thirds"
            3) selecting one from each third
            4) randomly selecting from the list up to self.choices    
            *) TODO: promoting restaurants without any votes        
        '''
        votedate = self.today()
        restaurants = db.query(Restaurant).all()

        #Select restaurants out of the noRepeatWeeks range                
        validRestaurants = [R for R in restaurants if R.last <= votedate - timedelta(1+cfg.norepeat)]        
        ranked = sorted(validRestaurants, key=lambda I:I.rank, reverse=True)

        #Divide into "thirds"
        third = len(ranked)/3
        choices = [random.choice(ranked[:third]),
                   random.choice(ranked[third:-third]),
                   random.choice(ranked[-third:])]
        ranked = [R for R in ranked if R not in choices]
        new = [R for R in ranked if R.visits==0]
        
        #TODO: instead of picking two random ones here, get a list of
        # "unvisited" places and pick from that.
        # If more are still required, randomly pick from what's left.
        choices.extend(random.sample(ranked, 5-3))
        random.shuffle(choices)
        return choices

    def calculate(self, db):
        '''Calculate the winner for this event based on current votes'''

        #return a dict of all votes for all users for a single event
        votes = {}
        event_votes = db.query(User.name, Vote.rank, Choice.num, Restaurant.name).join(Vote).join(Choice).join(Restaurant).filter(Vote.event==self.eventid)

        if event_votes.count() > 0:
            for name, rank, i, rest in event_votes.all():
                entry = votes.get(name, {})
                entry[rest] = rank
                votes[name] = entry
        
            #Format the list into the input for Schulze
            input = []
            for v in votes:
                input.append({"count":1, "ballot":copy(votes[v])})

            #Randomly select a tie-breaker user among those tied for the lowest tb_count            
            users = db.query(User).order_by(User.tb_count).all()
            users = [U for U in users if U.tb_count == users[0].tb_count]
            tb_user = random.choice(users)

            tb_votes = event_votes.filter(Vote.user == tb_user.id).order_by(Vote.rank.desc()).all()
            tb_list = [x[3] for x in tb_votes]        

            #Update the user's tb_count
            tb_user.tb_count += 1
            db.commit()

            output = SchulzeMethod(input, tie_breaker=tb_list, ballot_notation="rating").as_dict()
            return output['winner'], tb_user.name
        else:
            #No votes?!
            return None, ""        

class Lunch(object):
    ''' This object encapsulates the entire website '''
    def header(self, title="Lunch", subtitle=""):
        title = "%s%s"%(title, (": " + subtitle) if subtitle else "")
        head = '''<html><head>
        <title>%s</title>
        <link rel="stylesheet" href="static/style.css"/>
        </head>'''%title   
        head += "<body><div id=header>%s</div>"%(title) 
        head += "<div id=menu>"
        # head += "<div class=menu_button><a href=/admin>Admin</a></div>"
        head += "<div class=menu_button><a href=/results>Results</a></div>"
        head += "<div class=menu_button><a href=/>Home</a></div>"
        head += "</div>"
        return head

    def footer(self):
        #foot = '<div id=footer>Lunch</div></body></html>'
        foot = '</body></html>'
        return foot

    @cherrypy.expose
    def index(self):
        db = cherrypy.request.db
        datelimit = datetime.today() - timedelta(cfg.norepeat)        

        #Recalculate the restaurant ranking
        calculateRank(db, update=True)

        # site = "<html><head><title>Lunch</title></head>"
        site = self.header("Lunch")
        
        site += '<h2>Restaurant Leaderboard</h2><br/>'
        site += '<table>'
        site += '<tr><th>Rank</th><th>Restaurant</th><th>Visits</th><th>Last Visit</th></tr>'
        query = db.query(Restaurant).order_by(Restaurant.rank.desc())        
        for row in query.all():
            rank = 1
            site += '<tr>'
            site += '<td>%.2f</td>'%(row.rank)
            site += '<td>%s</td>'%(row.name)
            site += '<td>%d</td>'%(row.visits)
            site += '<td>%s</td>'%(row.last)            
            site += '</tr>'
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
        ''' 
        The vote page takes in an email address as parameter u.
        Displays a vote dialog with no action; enters/replaces a vote when
        action="vote"
        '''
        db = cherrypy.request.db
        event = cherrypy.engine.publish("get-event")[0]

        #voteinput[x] is the rank (1-5) of choice[x] or None
        try:
            voteinput = [int(args["c%d"%i]) if "c%d"%i in args else None for i in range(5)]
        except ValueError:
            voteinput = [None, None, None, None, None]

        site = self.header("Lunch", "Vote") 

        #TODO: Verify the user is in the Users table and check if they've voted in this event already        
        person = db.query(User).filter_by(email=u).one_or_none()
        if person is None:
            site += "<h2>You aren't allowed to vote</h2>"            
        else:
            site += "<h2>Hello, %s</h2>"%(person.name)                        

            if event is None:
                site += "<h3>Voting is closed!</h3>"
            else:
                oldvotes = db.query(Vote).join(User).filter(Vote.event==event.id, User.email==u).all()

                if action=='vote' and all(voteinput):
                    # SUBMITTING A VOTE
                    newvotes = [Vote(user=person.id, event=event.id, choice=event.choices[i].id, rank=voteinput[i]) for i in range(5)]

                    if len(oldvotes)==0:
                        site += "<h2>Vote received!</h2>"
                        db.add_all(newvotes)
                    else:
                        site += "<h2>Updated vote received!</h2>"
                        [db.delete(v) for v in oldvotes]
                        db.add_all(newvotes)

                    #Display the received vote for verification
                    site += '<table>'      
                    for restaurant, rank in db.query(Restaurant.name, Vote.rank).join(Choice).join(Vote).join(Event).filter(Event.id==event.id, Vote.user==person.id).all():
                        site += '''<tr>                
                            <td>%s</td>
                            <td>%s</td>                        
                        </tr>'''%(restaurant,rank)
                    site += '</table>'    

                    # cherrypy.engine.publish("calculate")              

                else:
                    # Display the vote table for the user
                    # If incomplete voteinput was passed in already, populate the table with it
                    site += "<h2>Lunch Vote for %s</h2>"%(event.date)
                    if len(oldvotes) > 0:
                        site += "<h3>You have already voted, but you can change your vote.</h3>"
                    if any(voteinput):
                        site += "<h3>You must rank all choices before voting.</h3>"
                    site += '''<p>Vote below by ranking each of these restaurants from 1 to 5, 
                    where 1 is "Meh," and 5 is "I really want to go here!" You can give multiple
                    restaurants the same rank if you like them equally. The rank you give
                    restaurants will affect their future rankings.</p>
                    <p>If you aren't able to attend this week, please don't vote.</p>'''
                    site += '<form method="post" action="vote">\n'
                    site += '<input type="hidden" name="u", value="%s">\n'%u
                    site += '<table class=table_vote>\n'
                    site += '<tr><th/><th>1</th><th>2</th><th>3</th><th>4</th><th>5</th>\n'
                    for i, restaurant in enumerate(db.query(Restaurant.name).join(Choice).filter(Choice.event==event.id).all()):
                        site += '<tr><td>%s</td>\n'%(restaurant.name)
                        for value in range(1,6):
                            site += '<td><input type="radio" name="c%d" value="%d" %s></td>\n'%(
                                i, value,
                                "checked" if "c%d"%i in args and str(value)==args["c%d"%i] else "")
                        site += '</tr>\n'
                    site += '</table>\n'
                    site += '<button type="submit" name="action" value="vote">Vote</button>\n'
                    site += '</form>\n'

        site += self.footer()
        return site

    def results_table(self, site, event):
        '''
        This helper prints a table of votes for the input event
        '''

        db = cherrypy.request.db

        site += '<h2>%s</h2>'%(event.date)

        #print out the header row (restaurant names)
        site += "<table class=table_results>\n"
        # site += "<caption>Votes recorded</caption>"
        site += "<tr><th/>"
        for c in event.choices:
            site += "<th>%s</th>"%(db.query(Restaurant).join(Choice).filter(Choice.id==c.id).one().name)
        site += "</tr>\n"

        #print out the votes (user name, rank, rank, rank, etc.)
        #build a dictionary from a query and then display that.

        #return a list of all votes for all users for a single event
        votes = {}
        for name, rank, i in db.query(User.name, Vote.rank, Choice.num).join(Vote).join(Choice).filter(Vote.event==event.id).all():
            entry = votes.get(name, [-1, -1, -1, -1, -1])
            entry[i] = rank
            votes[name] = entry

        for u in sorted(votes.keys()):
            site += "<tr>"
            site += "<td>%s</td>"%u
            for i in range(5):
                site += "<td>%d</td>"%(votes[u][i])
            site += "</tr>\n"
        site += "</table>\n"

        return site

    @cherrypy.expose
    def results(self, count=10):
        db = cherrypy.request.db
        
        #Current Event        
        currentevent = cherrypy.engine.publish("get-event")[0]
            
        #All Events
        events = db.query(Event).order_by(Event.date.desc(), Event.id.desc()).all()
        
        site = self.header("Lunch", "Results")
        for event in events:
            if currentevent is not None and event.id == currentevent.id:
                site += "<h2>Current Event</h2>"
            site = self.results_table(site, event)
        
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
        elif action == 'add_restaurant':
            rows = db.query(Restaurant).filter(Restaurant.name==name).all()
            if len(rows) == 0:
                if not date:
                    date = "1900-01-01"
                date = datetime.strptime(date,"%Y-%m-%d")
                print "ADD", name, visits, date
                R = Restaurant(name=name, visits=visits, last=date)
                db.add(R)
            else:
                site += "Restaurant \"%s\" already in database!<br/>"%name
        elif action == 'del_restaurant':
            for row in db.query(Restaurant).filter(Restaurant.name==name).all():
                db.delete(row)
        elif action == 'add_person':
            P = User(name=name, email=email)
            db.add(P)
        elif action == 'del_person':
            for row in db.query(User).filter(User.name==name).all():         
                db.delete(row)

        site += '<hr/>Restaurants in the list:<br/>'
        site += '<table>'
        site += '<tr><th/><th>Rank</th><th>Restaurant</th><th>Visits</th><th>Last Visit</th><th>Added</th></tr>'
        Q = db.query(Restaurant).order_by(Restaurant.visits.desc())
        R = [(K,0) for K in Q]
        for row, rank in R:
            site += '''<tr>
                <td>                    
                    <form style="float:right" method="post" action="admin">
                        <input type="hidden" name="name" value="%s">
                        <button type="submit" name="action" value="del_restaurant" onclick="return confirm('Are you sure you want to remove %s?');">X</button>
                    </form>
                </td>'''%(row.name, row.name)
            site += '<td>%d</td>'%(rank)
            site += '<td>%s</td>'%(row.name)
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
        site += '<tr><th/><th>Name</td><th>Email</th><th>Tiebreaks</th></tr>'
        Q = db.query(User).order_by(User.name)
        for row in Q:
            site += '''<tr>
                <td>                    
                    <form style="float:right" method="post" action="admin">
                        <input type="hidden" name="name" value="%s">
                        <button type="submit" name="action" value="del_person" onclick="return confirm('Are you sure you want to remove user %s?');">X</button>
                    </form>
                </td>'''%(row.name, row.name)
            site += '<td>%s</td>'%(row.name)
            site += '<td>%s</td>'%(row.email)
            site += '<td>%d</td>'%(row.tb_count)    
            site += '</tr>'
        site += '</table>'
        site += '</br>'
        site += '''<form method="post", action="admin">
            Name<input type="text" name="name" required>
            Email<input type="email" name="email">            
            <button type="submit" name="action" value="add_person">Add User</button>
            </form>'''  

        site += self.footer()
        return site


if __name__ == '__main__':
    #Authorized user(s) for the admin page
    userpassdict = {'admin' : 'admin'}

    #Accept all inputs
    cherrypy.config.update({'server.socket_host': '0.0.0.0',
                        'server.socket_port': 8080,
                       })

    conf = {
        '/': {
            'tools.db.on': True
        },

        '/admin': {
            'tools.auth_digest.on': True,
            'tools.auth_digest.realm': 'lunch',
            'tools.auth_digest.get_ha1': cherrypy.lib.auth_digest.get_ha1_dict_plain(userpassdict),
            'tools.auth_digest.key': 'd8f0238a5c3bae97',
        },

        '/static': {
            'tools.staticdir.on': True,
            'tools.staticdir.dir': os.path.join(os.getcwd(), "static")
        }
    }

    Manager(cherrypy.engine, 1).subscribe()
    SAEnginePlugin(cherrypy.engine, 'sqlite:///'+cfg.dbfile).subscribe()
    cherrypy.tools.db = SATool()
    cherrypy.quickstart(Lunch(), '/', conf)