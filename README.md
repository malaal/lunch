![Lunch Today](https://github.com/malaal/lunchtoday/blob/master/static/lunchtoday_full.png) 
## Lunch Today
### What's for lunch today?

Web-based lunch voting system for Python, using SQLAlchemy/SQLite and CherryPy. Runs as it's own webserver and stores it's data in a DB. On designed days, sends out an email to a group of people with a list of restaurant choices and directs them to the website to submit their votes.

Still a work in progress, but good enough to solve your lunch decisions. See [The TODO list](TODO.md) for a look at what's to come.

### Requirements
Install these however you prefer to install Python modules.
* Python 2.7
* python-vote-full
* SQLAlchemy
* CherryPy

### Installation
1. Clone this repo somewhere.
2. Copy lunchconfig_defaults.json to lunchconfig.json and edit it:
    - lunch: web server settings
        - hostname: The hostname of the server; will be used as the URL for emailed links
        - dbfile: The path to the sqlite db file
        - norepeat: The number of days after a restaurant is selected before it is allowed to show up again for a vote
        - time_days: A list of days of the week to run voting events (0=Monday, 1=Tuesday, etc)
        - time_start: The time of the day to open voting. Expressed as a list: [Hour, Minute] on a 24h clock. Be careful not to put leading zeroes! For example, enter [9,0] for 9:00.
        - time_end: The time of the day to close voting.
    - smtp: outgoing mail server settings
        - server: Your outgoing SMTP server
        - port: The port to connect (probably 465)
        - user: SMTP server username
        - pass: SMTP server password
3. Run lunch.py
4. Navigate to http://hostname:8080/admin and start adding restaurants and users to email (user/pass admin:admin).
5. The vote automatically starts when it's time for lunch
