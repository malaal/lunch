import json
import os
from datetime import time

class LunchConfig(object):
	_defaults = '''{
	  "lunch": {
	  	"hostname"   : "localhost",
	    "dbfile"     : "lunch.db",
	    "norepeat"   : 21,
	    "time_days"  : [3],
	    "time_start" : [9,30],
	    "time_end"   : [11,0]
	  },

	  "smtp": {
	    "server"     : "smtpserver",
	    "port"       : 465,
	    "user"       : "user",
	    "pass"       : "password"
	  }
	}'''

	def __init__(self, cfgfile="lunchconfig.json"):
		self.config = json.loads(self._defaults)
		self.cfgfile = cfgfile

		if os.path.exists(cfgfile):
			with open(cfgfile,'r') as F:
				self.config = json.load(F)

	def __str__(self):
		return str(self.config)	

	def save(self):
		with open(self.cfgfile,'w') as F:
			F.write(json.dumps(self.config, indent=2))

	@property 
	def dbfile(self): 
		return self.config['lunch']['dbfile']

	@property 
	def hostname(self): 
		return self.config['lunch']['hostname']

	@property 
	def norepeat(self): 
		return self.config['lunch']['norepeat']

	@property 
	def time_days(self): 
		return self.config['lunch']['time_days']

	@property 
	def time_start(self): 
		return time(*self.config['lunch']['time_start'])

	@property 
	def time_end(self): 
		return time(*self.config['lunch']['time_end'])

	@property
	def smtp(self): 
		return self.config['smtp']	


def main():	
	cfg = LunchConfig("lunchconfig_defaults.json")
	cfg.save()
	print "hostname      ",cfg.hostname
	print "dbfile        ",cfg.dbfile
	print "norepeat      ",cfg.norepeat
	print "time_days     ",cfg.time_days
	print "time_start    ",cfg.time_start
	print "time_end      ",cfg.time_end
	print "smtp          ",cfg.smtp

if __name__ == '__main__':
	main()