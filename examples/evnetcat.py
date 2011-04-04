
import sys
import logging
import traceback
logging.basicConfig(level=logging.DEBUG)

from evnet import PlainClientConnection, loop, unloop

def filegen(fobj):
	d = fobj.read(1024**2)
	while d:
		yield d
		d = fobj.read(1024**2)

class Filesender(object):
	def __init__(self, host, port, fp):
		self.fobj = open(fp, 'rb')
		self.c = PlainClientConnection((host, port))
		self.c._on('writable', self.send_data)
		self.c._on('ready', self.ready)
		self.c._on('close', self.closed)

	def ready(self):
		print 'connection ready, pumping'
		self.send_data()

	def send_data(self):
		d = self.fobj.read(16384)
		if not d:
			print 'EOF, closing'
			self.fobj.close()
			self.c.close()
			unloop()
			return
		self.c.write(d)
	def closed(self, e):
		traceback.print_exc()
		print e
		self.fobj.close()
		unloop()

a = Filesender(sys.argv[1], int(sys.argv[2]), sys.argv[3])

loop()

