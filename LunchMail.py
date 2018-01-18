#/usr/bin/python
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

class LunchMail(object):
	def __init__(self, server, port, user, password):
		self.server = server
		self.port = port
		self.user = user
		self.password = password

	def _send(self, fromaddr, toaddr, msg):
		try: 
			s = smtplib.SMTP()
			s.connect(self.server, self.port)
			# s.set_debuglevel(True)
			s.ehlo_or_helo_if_needed()
			s.starttls()
			s.ehlo_or_helo_if_needed()
			s.login(self.user, self.password)
			s.sendmail(fromaddr, toaddr, msg.as_string())
			s.quit()
		except Exception, e:
			print e

	def sendhtml(self, toaddr, subject, body, fromaddr=None, alt_text=None, test=False):	
		if fromaddr is None:
			fromaddr = self.user			
		msg = MIMEMultipart('alternative')
		msg['Subject'] = subject
		msg['From'] = self.user
		msg['To'] = ",".join(toaddr)
		msg.attach(MIMEText(body, 'html'))
		if alt_text is not None:
			msg.attach(MIMEText(alt_text, 'text'))
		
		if not test:
			self._send(fromaddr, toaddr, msg)
		else:
			print "TEST EMAIL:"
			print "From:    ", fromaddr
			print "To:      ", ",".join(toaddr)
			print "Subject: ", subject
			print "-----"
			print body

	def sendtext(self, toaddr, subject, body, fromaddr=None, test=False):
		if fromaddr is None:
			fromaddr = self.user			
		msg = MIMEText(body)
		msg['Subject'] = subject
		msg['From'] = self.user
		msg['To'] = ",".join(toaddr)

		if not test:
			self._send(fromaddr, toaddr, msg)
		else:
			print "TEST EMAIL:"
			print "From:    ", fromaddr
			for ta in toaddr:
				print "To:      ", ta
			print "Subject: ", subject
			print "-----"
			print body
