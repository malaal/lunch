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
from time import sleep
import random
import os
from copy import copy
from collections import Counter

### DEBUG
DEBUG = False
### DEBUG

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
        ranks = db.query(Vote.rank).join(Restaurant).filter(Restaurant.name==rest.name)
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

def calculateVote(db, event, break_ties=False):
    '''Calculate the winner for this event based on current votes'''

    #return a dict of all votes for all users for a single event
    votes = {}
    event_votes = db.query(User.name, Vote.rank, Restaurant.name).join(Vote).join(Restaurant).filter(Vote.event==event.id)

    if event_votes.count() > 0:
        for user, rank, rest in event_votes.all():
            entry = votes.get(user, {})
            entry[rest] = rank
            votes[user] = entry
    
        #Format the list into the input for Schulze
        input = []
        for v in votes:
            input.append({"count":1, "ballot":copy(votes[v])})

        output = SchulzeMethod(input, ballot_notation="rating").as_dict()
        tb_user = None

        if "tied_winners" in output and break_ties:            
            #Randomly select a tie-breaker user among those voters tied for the lowest tb_count            
            users = db.query(User).join(Vote).filter(Vote.event==event.id).order_by(User.tb_count).all()
            users = [U for U in users if U.tb_count == users[0].tb_count]
            tb_user = random.choice(users)

            tb_votes = event_votes.filter(Vote.user == tb_user.id).order_by(Vote.rank.desc()).all()
            tb_list = [x[2] for x in tb_votes]        

            #Update the user's tb_count
            tb_user.tb_count += 1
            db.commit()

            output = SchulzeMethod(input, tie_breaker=tb_list, ballot_notation="rating").as_dict()

        return output, tb_user

    else:
        #No votes?!
        return None, ""    

class Manager(Monitor):
    ''' 
    This CherryPy plugin manages creation and operation of vote sessions.
    Is is set up to be run twice a minute, and operates based on the 
    current time and day, and values of LunchConfig
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
        super(Manager, self).start()

    def stop(self):
        self.bus.unsubscribe("get-event", self.getEvent)        
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
        #Returns the day of the week (0==Monday) and the current time
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
            <h1>Lunch Today!</h1>
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
            self.mail.sendhtml([user.email], "Lunch Vote Open %s"%event.date, email, test=DEBUG)
            sleep(15)

    def endVote(self, db):
        self.bus.log("*** Voting has closed!")
        event = self.getEvent()
        results, tb_user = calculateVote(db, event, True)
            
        if results is None:
            self.bus.log("Received no votes!")
        else:
            winner = results['winner']        
            
            #Increment the restaurant's win list and visited date
            rest = db.query(Restaurant).filter(Restaurant.name==winner).one_or_none()        
            rest.visits += 1
            rest.last = datetime.today()

            event.winner = rest
            event.tie_breaker = tb_user
            db.commit()

            #Recalculate the restaurant ranking
            calculateRank(db, update=True)

            #Email the users who voted only
            attendees = db.query(User).join(Vote).filter(Vote.event==event.id).all()
            email = '''
            <html><body>
            <h1>Lunch Today:<br/>%s</h1>
            <p>The lunch ballot is closed for %s.</p>
            <p>Who is coming today:
                <ul>
            '''%(winner, event.date)
            for user in attendees:
                email += "<li>%s</li>"%(user.name)
            email +='''
                </ul>
            </p>
            '''

            if tb_user is not None:
                email += "<p>This week's tie-breaker was: %s</p>"%(tb_user.name)
            
            email += "</body></html>"            

            self.bus.log("Emailing Results")
            self.mail.sendhtml([user.email for user in attendees], "Lunch Vote Closed %s"%event.date, email, test=DEBUG)

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

        #Select restaurants out of the noRepeatWeeks range, and sort by rank                
        validRestaurants = [R for R in restaurants if R.last <= votedate - timedelta(1+cfg.norepeat)]        
        ranked = sorted(validRestaurants, key=lambda I:I.rank, reverse=True)

        #Divide into "thirds"
        third = len(ranked)/3
        choices = [random.choice(ranked[:third]),
                   random.choice(ranked[third:-third]),
                   random.choice(ranked[-third:])]

        rem = [R for R in ranked if R not in choices]
        ranked = [R for R in rem if R.rank > 0]
        new = [R for R in rem if R.rank==0]
        
        #Attempt to pad the list with "new" restaurants (ie: ones that have no votes)
        if len(new) >= 2:
            choices.extend(random.sample(new, 2))
        else:
            #Not enough new restaurants; randomly select from the rest
            choices.extend(new)
            choices.extend(random.sample(ranked, 5-len(choices)))

        #randomize the output!            
        random.shuffle(choices)
        return choices

class Lunch(object):
    ''' This object encapsulates the entire website '''

    def header(self, title="Lunch Today", subtitle=""):
        #Common header HTML
        pagetitle = "%s%s"%(title, (": " + subtitle) if subtitle else "")
        head = '''<html><head>
        <title>%s</title>
        <link rel="stylesheet" href="static/style.css"/>
        <link rel="apple-touch-icon" sizes="180x180" href="/static/apple-touch-icon.png">
        <link rel="icon" type="image/png" sizes="32x32" href="/static/favicon-32x32.png">
        <link rel="icon" type="image/png" sizes="16x16" href="/static/favicon-16x16.png">
        <link rel="manifest" href="/static/manifest.json">
        <link rel="mask-icon" href="/static/safari-pinned-tab.svg" color="#cf9e5c">
        <link rel="shortcut icon" href="/static/favicon.ico">
        <meta name="msapplication-config" content="/static/browserconfig.xml">
        <meta name="theme-color" content="#ffffff">        
        </head>'''%pagetitle   
        head += "<body><div id=header><b>%s</b>"%(title) 
        if subtitle:
            head += ": %s</div>"%subtitle
        else:
            head += "</div>"
        head += "<div id=menu>"
        # head += "<div class=menu_button><a href=/admin>Admin</a></div>"
        head += "<div class=menu_button><a href=/results>Results</a></div>"
        head += "<div class=menu_button><a href=/>Home</a></div>"
        head += "</div>"
        return head

    def footer(self):
        #Common footer HTML
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
        site = self.header()
        
        site += '<h2>Restaurant Leaderboard</h2><br/>'
        site += '<table>'
        site += '<tr><th>Rank</th><th>Restaurant</th><th>Visits</th><th>Last Visit</th></tr>'
        query = db.query(Restaurant).order_by(Restaurant.rank.desc())        
        for row in query.all():
            rank = 1
            site += '<tr>'
            site += '<td>%.2f</td>'%(row.rank)
            if row.website:
                site += '<td><a href=%s>%s</a></td>'%(row.website, row.name)    
            else:
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

        site = self.header(subtitle="Vote") 

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
                    newvotes = [Vote(user=person.id, event=event.id, restaurant=event.choices[i].restaurant, rank=voteinput[i]) for i in range(5)]

                    if len(oldvotes)==0:
                        site += "<h2>Vote received!</h2>"
                        db.add_all(newvotes)
                    else:
                        site += "<h2>Updated vote received!</h2>"
                        [db.delete(v) for v in oldvotes]
                        db.add_all(newvotes)

                    #Display the received vote for verification
                    site += '<table>'      
                    #for rest, rank in db.query(Restaurant.name, Vote.rank).join(Choice).join(Vote).join(Event).filter(Event.id==event.id, Vote.user==person.id).order_by(Choice.num).all():
                    for rest, rank in db.query(Restaurant.name, Vote.rank).join(Vote).filter(Vote.event==event.id, Vote.user==person.id).all():
                        site += '''<tr>                
                            <td>%s</td>
                            <td>%s</td>                        
                        </tr>'''%(rest,"&#9733;"*rank)
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
                    site += '''<p>Vote below by ranking each of these restaurants with a number of stars, 
                    where &#9733; is "Meh," and &#9733;&#9733;&#9733;&#9733;&#9733; is "I really want to go here!"</p>
                    <p>Your restaurant choice for this week will be the highest-ranked choice(s) voted for. If you're forced to pick the lesser of two evils, rank them accordingly!</p>
                    <p>You can give multiple restaurants the same rank if you like them equally. 
                    The rank you give restaurants will affect their future rankings.</p>
                    <p>If you aren't able to attend this week, please don't vote.</p>'''
                    site += '<form method="post" action="vote">\n'
                    site += '<input type="hidden" name="u", value="%s">\n'%u
                    site += '<table class=table_vote>\n'
                    site += '''<tr><th/>
                    <th>&#9733;&#9733;&#9733;&#9733;&#9733;</th>
                    <th>&#9733;&#9733;&#9733;&#9733;</th>
                    <th>&#9733;&#9733;&#9733;</th>
                    <th>&#9733;&#9733;</th>
                    <th>&#9733;</th>
                    '''
                    for i, rest in enumerate(db.query(Restaurant).join(Choice).filter(Choice.event==event.id).order_by(Choice.num).all()):
                        if rest.website:
                            site += '<tr><td><a href=%s>%s</a></td>'%(rest.website, rest.name)    
                        else:
                            site += '<tr><td>%s</td>'%(rest.name)
                        for value in range(5,0,-1):
                            site += '<td><input type="radio" name="c%d" value="%d" %s></td>\n'%(
                                i, value,
                                "checked" if "c%d"%i in args and str(value)==args["c%d"%i] else "")
                        site += '</tr>\n'
                    site += '</table>\n'
                    site += '<button type="submit" name="action" value="vote">Vote</button>\n'
                    site += '</form>\n'

        site += self.footer()
        return site

    def results_table(self, event):
        '''
        This helper prints a table of votes for the input event
        '''

        db = cherrypy.request.db

        site = '<hr/><h3>Votes Collected</h3>'

        #print out the header row (restaurant names)
        site += "<table class=table_results>\n"
        # site += "<caption>Votes recorded</caption>"
        site += "<tr><th/>"

        restaurants = [db.query(Restaurant).join(Choice).filter(Choice.id==c.id).one().name for c in event.choices]

        for r in restaurants:
            site += "<th>%s</th>"%(r)
        site += "</tr>\n"

        #print out the votes (user name, rank, rank, rank, etc.)
        #build a dictionary from a query and then display that.

        #return a list of all votes for all users for a single event
        votes = {}        
        for name, rank, rest in db.query(User.name, Vote.rank, Restaurant.name).join(Vote).join(Restaurant).filter(Vote.event==event.id).all():
            entry = votes.get(name, [-1, -1, -1, -1, -1])
            entry[restaurants.index(rest)] = rank
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
    def results(self, evtid=None, count=10):
        db = cherrypy.request.db
        
        #Current Event        
        currentevent = cherrypy.engine.publish("get-event")[0]
        selectedevent = None

        #Set the selectedevent; it might end up being None!
        if evtid is None:
            if currentevent is not None:
                selectedevent = currentevent
            else:
                selectedevent = db.query(Event).order_by(Event.id.desc()).first()
        else:
            selectedevent = db.query(Event).filter(Event.id==evtid).one_or_none()
            
        #All Events
        events = db.query(Event).order_by(Event.date.desc(), Event.id.desc()).all()

        site = self.header(subtitle="Results")

        #Sidebar
        site += "<div id=results_sidebar>"
        site += "<h1>Event List</h1>"        
        if len(events)==0:
            site += "<p>No Events</p>"
        for event in events:
            site += "<p><a href=/results?evtid=%d>%s"%(event.id, event.date)
            if event.winner:
                site += ": %s"%(event.winner.name)
            site += "</a></p>"
        site += "</div>"

        site += "<div id=results_content>"
        if selectedevent is None:
            site += "<p>No events</p>"
        else:
            results, _ = calculateVote(db, selectedevent)            

            site += "<h1>Results for %s</h1>"%(selectedevent.date)
            if selectedevent.winner:
                site += "<h2>Winner: %s</h2>"%(selectedevent.winner.name)
            if results and 'tied_winners' in results:
                print results['tied_winners']
                site += "<p>Ties: "
                site += ", ".join(results['tied_winners'])
                site += "</p>"
            if selectedevent.tiebreaker:
                site += "<p>Tiebreaker: %s</p>"%(selectedevent.tiebreaker.name)
            site += self.results_table(selectedevent)
        site += "</div>"
        
        # for event in events:
        #     if currentevent is not None and event.id == currentevent.id:
        #         site += "<h2>Current Event</h2>"
        #     site = self.results_table(site, event)
        
        site += self.footer()
        return site

    @cherrypy.expose
    def admin(self, action="", name="", visits=0, date="", email="", **kwargs):
        db = cherrypy.request.db
        
        site = self.header(subtitle="Admin") 

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
    cherrypy.config.update({
        'server.socket_host': '0.0.0.0',
        'server.socket_port': 8080,
        })

    #Disable auto reload
    cherrypy.config.update({
        'global': {
            # 'environment' : 'production'
            'engine.autoreload.on': False,
        }
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

    if DEBUG:
        Manager(cherrypy.engine, 1).subscribe()
    else:
        Manager(cherrypy.engine, 60).subscribe()
    SAEnginePlugin(cherrypy.engine, 'sqlite:///'+cfg.dbfile).subscribe()
    cherrypy.tools.db = SATool()
    cherrypy.quickstart(Lunch(), '/', conf)