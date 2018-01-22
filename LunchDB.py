#!/usr/bin/python
import sqlite3
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy import create_engine
from sqlalchemy import event
from sqlalchemy import Column, Integer, String, Float, Date, Boolean, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql.expression import func
import os, os.path
from datetime import datetime

Base=declarative_base()
Session=sessionmaker()

__all__ = ['Restaurant', 'User', 'Event', 'Choice', 'Vote', 'LunchDB']

#TABLE: list of restaurants
class Restaurant(Base):
    __tablename__ = 'restaurants'
    id = Column(Integer, primary_key=True)
    name = Column(String(250), nullable=False)  #Restaurant Name
    rank = Column(Float, default=0.0)          #Current Rank (updated after each event)
    visits = Column(Integer, default=0)         #Number of visits (ie: number of votes won)
    last = Column(Date, default=datetime(1900,1,1)) #Date of last visit (if applicable)
    added = Column(Date, default=datetime.today())   #Date added to DB
    enabled = Column(Boolean, default=True, nullable=False) #Set to false once a restaurant is removed from all votes
    website = Column(String(500))  #Restaurant Name

#TABLE: List of users on this site
class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    name = Column(String(250))  #User's name
    email = Column(String(250)) #User's email address
    tb_count = Column(Integer, default=0) #Number of times this user was used to break a tie

    def __repr__(self):
        return "<User '%s' <%s>>"%(self.name, self.email)

#TABLE: list of vote events
#   with relationship to the choices and votes for this event
class Event(Base):
    __tablename__ = 'events'
    id = Column(Integer, primary_key=True)
    date = Column(Date, default=func.now())   #Date of event
    choices = relationship("Choice", backref="Event")
    votes = relationship("Vote", backref="Event")

    def __repr__(self):
        return "<Event {}>".format(self.date)

#TABLE: List of the choices mapped to vote events (each event has several)
class Choice(Base):
    __tablename__ = 'choices'
    id = Column(Integer, primary_key=True) 
    num = Column(Integer)
    event = Column(Integer, ForeignKey(Event.id))
    restaurant = Column(Integer, ForeignKey(Restaurant.id))
    votes = relationship("Vote", backref="Choice")

    def __repr__(self):
        return "<Choice %d is Event %d:%d>"%(self.id, self.event, self.num)

#TABLE: list of individual votes, tied to a specific Event/Choice
class Vote(Base):
    __tablename__ = 'votes'
    id = Column(Integer, primary_key=True)
    event = Column(Integer, ForeignKey(Event.id))
    choice = Column(Integer, ForeignKey(Choice.id))
    user  = Column(Integer, ForeignKey(User.id))
    rank = Column(Integer)

    def __repr__(self):
        return "<Vote %d:%d=%d by %s>"%(self.event,self.choice,self.rank,self.user)

class LunchDB(object):
    def __init__(self, dbfile):
        self.engine = create_engine('sqlite:///'+dbfile)
        Session.configure(bind=self.engine)
        Base.metadata.create_all(self.engine)


#
# These event listeners populate a demo dataset iff a new dbfile is created
#
@event.listens_for(Restaurant.__table__, 'after_create')
def demo_restaurant(target, connection, **kwargs):
    print "CREATING DEMO RESTAURANTS"
    session = Session()
    session.add(Restaurant(name="Pizza",      visits=10))
    session.add(Restaurant(name="Sandwiches", visits=8))
    session.add(Restaurant(name="Chinese",    visits=6))
    session.add(Restaurant(name="Mexican",    visits=5))
    session.add(Restaurant(name="Chicken",    visits=3))
    session.add(Restaurant(name="Italian",    visits=0))
    session.add(Restaurant(name="Vietnamese", visits=0))
    session.add(Restaurant(name="Japanese",   visits=3))
    session.commit()

@event.listens_for(Vote.__table__, 'after_create')
def demo_person(target, connection, **kwargs):
    print "CREATING DEMO PEOPLE"
    session = Session()
    session.add(User(name="Joe Test", email="jtest@test.com"))
    session.add(User(name="Bob Test", email="atest@test.com"))
    session.commit()        

@event.listens_for(Choice.__table__, 'after_create')
def demo_event(target, connection, **kwargs):
    print "CREATING DEMO EVENTS"
    session = Session()
    event = Event()
    event.choices = [
        Choice(num=0, restaurant=1),
        Choice(num=1, restaurant=3),
        Choice(num=2, restaurant=5),
        Choice(num=3, restaurant=2),
        Choice(num=4, restaurant=6)
        ]
    session.add(event)
    event2 = Event()
    event2.choices = [
        Choice(num=0, restaurant=2),
        Choice(num=1, restaurant=4),
        Choice(num=2, restaurant=3),
        Choice(num=3, restaurant=5),
        Choice(num=4, restaurant=1)
        ]
    session.add(event2)    
    session.commit()    

@event.listens_for(Vote.__table__, 'after_create')
def demo_vote(target, connection, **kwargs):
    print "CREATING DEMO VOTES"
    session = Session()
    event = session.query(Event).first()
    event.votes.append(Vote(user=1, rank=1, choice=event.choices[0].id))
    event.votes.append(Vote(user=1, rank=2, choice=event.choices[1].id))
    event.votes.append(Vote(user=1, rank=3, choice=event.choices[2].id))
    event.votes.append(Vote(user=1, rank=4, choice=event.choices[3].id))
    event.votes.append(Vote(user=1, rank=5, choice=event.choices[4].id))
    event.votes.append(Vote(user=2, rank=2, choice=event.choices[0].id))
    event.votes.append(Vote(user=2, rank=1, choice=event.choices[1].id))
    event.votes.append(Vote(user=2, rank=2, choice=event.choices[2].id))
    event.votes.append(Vote(user=2, rank=3, choice=event.choices[3].id))
    event.votes.append(Vote(user=2, rank=3, choice=event.choices[4].id))
    session.commit() 

#
# Code to test these features by running this directly
#

def main():
    L = LunchDB("lunch.db")
    db = Session()

    eid = 6

    #Return a list of all choices for a single event
    for r in db.query(Choice).join(Event).filter(Event.id==eid).all():
        print r
    #Return a list of all restaurant names for a single event
    for r in db.query(Restaurant.name).join(Choice).join(Event).filter(Event.id==eid).order_by(Choice.num).all():
        print r        
    #return a list of all votes for a single event
    for r in db.query(Vote, Choice).join(Choice).join(Event).filter(Event.id==eid).all():
        print r
    #return a list of all votes for a single event and user, by choice
    for r in db.query(Choice, Vote.rank).join(Vote).join(Event).filter(Event.id==eid, Vote.user==1).all():
        print r      
    #return a list of all votes for a single event and user, by restaurant name
    for r in db.query(Restaurant.name, Vote.rank).join(Choice).join(Vote).join(Event).filter(Event.id==eid, Vote.user==1).all():
        print r     

    print "---------------"
    #return a list of all votes for all users for a single event
    for u in db.query(Vote).join(User).filter(Vote.event==eid): 
        print u
    #return a list of all vote ranks for all users for a single event, with their choice number
    for u in db.query(User.name, Vote.rank, Choice.num).join(Vote).join(Choice).filter(Vote.event==eid): 
        print u
    #return a list of all vote ranks for all users for a single event, with their choice number and name
    for u in db.query(User.name, Vote.rank, Choice.num, Restaurant.name).join(Vote).join(Choice).join(Restaurant).filter(Vote.event==eid): 
        print u                   

    print "---------------"
    #return a list of all users who voted on a single event
    for u in db.query(User).join(Vote).filter(Vote.event==eid):
        print u

    print "---------------"
    #return a list of all votes for a single restaurant
    for v in db.query(Vote.rank).join(Choice).join(Restaurant).filter(Restaurant.name=="Dominic's of New York").all():
        print v

if __name__ == '__main__':
    main()