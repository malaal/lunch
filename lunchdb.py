#!/usr/bin/python
import sqlite3
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from sqlalchemy import event
from sqlalchemy import Column, Integer, String, Date, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
import os, os.path
from datetime import datetime

Base=declarative_base()
Session=sessionmaker()

__all__ = ['Restaurant', 'Person', 'Event', 'Vote', 'LunchDB']

#TABLE: list of restaurants
class Restaurant(Base):
    __tablename__ = 'restaurants'
    id = Column(Integer, primary_key=True)
    name = Column(String(250), nullable=False)  #Restaurant Name
    visits = Column(Integer, default=0)         #Number of visits (ie: number of votes won)
    votes = Column(Integer, default=0)          #Number of times it appeared for a vote
    last = Column(Date, default=datetime(1900,1,1)) #Date of last visit (if applicable)
    added = Column(Date, default=datetime.today())   #Date added to DB

#TABLE: List of people who are emailed to vote
class Person(Base):
    __tablename__ = 'people'
    id = Column(Integer, primary_key=True)
    name = Column(String(250))  #Person's name
    email = Column(String(250)) #Person's email address

#TABLE: list of vote events
class Event(Base):
    __tablename__ = 'events'
    id = Column(Integer, primary_key=True)
    choice1 = Column(Integer, ForeignKey(Restaurant.id))
    choice2 = Column(Integer, ForeignKey(Restaurant.id))
    choice3 = Column(Integer, ForeignKey(Restaurant.id))
    choice4 = Column(Integer, ForeignKey(Restaurant.id))
    choice5 = Column(Integer, ForeignKey(Restaurant.id))

    def getChoices(self):
        return [self.choice1, self.choice2, self.choice3, self.choice4, self.choice5]

#TABLE: list of individual votes, tied to an event
class Vote(Base):
    __tablename__ = 'votes'
    id = Column(Integer, primary_key=True)
    user  = Column(Integer, ForeignKey(Person.id))
    event = Column(Integer, ForeignKey(Event.id))
    rank1 = Column(Integer)
    rank2 = Column(Integer)
    rank3 = Column(Integer)
    rank4 = Column(Integer)
    rank5 = Column(Integer)

class LunchDB(object):
    def __init__(self, dbfile):
        self.engine = create_engine('sqlite:///'+dbfile)
        Session.configure(bind=self.engine)
        Base.metadata.create_all(self.engine)

@event.listens_for(Restaurant.__table__, 'after_create')
def demo_restaurant(target, connection, **kwargs):
    print "CREATING DEMO RESTAURANTS"
    session = Session()
    session.add(Restaurant(name="Pizza",      votes=10, visits=10))
    session.add(Restaurant(name="Sandwiches", votes=8,  visits=8))
    session.add(Restaurant(name="Chinese",    votes=8,  visits=6))
    session.add(Restaurant(name="Mexican",    votes=10, visits=5))
    session.add(Restaurant(name="Chicken",    votes=10, visits=3))
    session.add(Restaurant(name="Italian",    votes=5,  visits=0))
    session.add(Restaurant(name="Vietnamese", votes=10, visits=0))
    session.add(Restaurant(name="Japanese",   votes=3,  visits=3))
    session.commit()

@event.listens_for(Event.__table__, 'after_create')
def demo_event(target, connection, **kwargs):
    print "CREATING DEMO EVENTS"
    session = Session()
    session.add(Event(choice1=0, choice2=1, choice3=4, choice4=2, choice5=3))
    session.commit()    

@event.listens_for(Event.__table__, 'after_create')
def demo_person(target, connection, **kwargs):
    print "CREATING DEMO PEOPLE"
    session = Session()
    session.add(Person(name="Joe Test", email="jtest@test.com"))
    session.add(Person(name="Andrew Test", email="atest@test.com"))
    session.commit()        