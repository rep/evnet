from evnet import ClientConnection, loop, unloop

c = ClientConnection(('127.0.0.1', 20001), cert='./cert2.pem')

def readycb(fp):
	print 'ready, remote fp: %s' % fp
	c.write('test\n')
	c.close()

def closecb(r):
	print 'closed', r
	unloop()

c._on('close', closecb)
c._on('ready', readycb)

loop()

