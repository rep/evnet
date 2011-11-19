
from evnet import loop, unloop, pyev, default_loop, EVException, EventGen, later

import sys
import os
import subprocess
import traceback
import fcntl
import errno

def fdnonblock(fd):
	fcntl.fcntl(fd, fcntl.F_SETFL, fcntl.fcntl(fd, fcntl.F_GETFL) | os.O_NONBLOCK)

class Process(EventGen):
	def __init__(self, args):
		EventGen.__init__(self)

		self.buf = bytearray()
		self._writing = False
		self._closed = False
		self.retval = None
		try:
			self.p = subprocess.Popen(args, stdin=subprocess.PIPE,
				stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False)
		except Exception, e:
			self._closed = True
			self.retval = 3
			self._event('close', e)
		else:
			self.cw = pyev.Child(self.p.pid, False, default_loop, self.cw_cb)
			self.orw = pyev.Io(self.p.stdout, pyev.EV_READ, default_loop, self.orw_cb, priority=pyev.EV_MINPRI)
			self.erw = pyev.Io(self.p.stderr, pyev.EV_READ, default_loop, self.erw_cb, priority=pyev.EV_MINPRI)
			self.iww = pyev.Io(self.p.stdin, pyev.EV_WRITE, default_loop, self.iww_cb, priority=pyev.EV_MINPRI)
			fdnonblock(self.p.stdin.fileno())
			fdnonblock(self.p.stdout.fileno())
			fdnonblock(self.p.stderr.fileno())

			self.cw.start()
			self.orw.start()
			self.erw.start()

	def kill(self):
		try: self.p.kill()
		except OSError, e: self._close(e)
	def terminate(self):
		try: self.p.terminate()
		except OSError, e: self._close(e)

	def write(self, data):
		if self._closed: raise EVException('Already closed.')
		if not isinstance(data, bytes): data = bytes(data)
		self.buf.extend(data)
		if not self.iww.active and not self._writing: self._writeloop()
		
	def forward(self, fd, ed, watcher):
		count = 0
		while not self._closed and count < 5:
			count += 1
			try: data = fd.read(16384)
			except IOError as e:
				if e.errno == errno.EAGAIN: return
				else:
					watcher.stop()
					self._close(EVException('Exception {0}'.format(e)))
			except Exception as e:
				watcher.stop()
				self._close(EVException('Exception {0}'.format(e)))
			else:
				if not data: watcher.stop()
				else:
					try: self._event(ed, data)
					except:	traceback.print_exc()

	def cw_cb(self, watcher, events):
		if os.WIFSIGNALED(watcher.rstatus): self.retval = -os.WTERMSIG(watcher.rstatus)
		elif os.WIFEXITED(watcher.rstatus): self.retval = os.WEXITSTATUS(watcher.rstatus)
		self._close(EVException('Child exit.'))
		
	def orw_cb(self, watcher, events):
		self.forward(self.p.stdout, 'read', watcher)

	def erw_cb(self, watcher, events):
		self.forward(self.p.stderr, 'readerr', watcher)

	def iww_cb(self, watcher, events):
		if self.iww.active: self.iww.stop()

		try: self._writeloop()
		except:
			traceback.print_exc()
			self._close(EVException('DEBUGWRAP'))

	def _writeloop(self):
		self._writing = True
		count = 0
		while not self._closed and len(self.buf)>0 and count < 5:
			count += 1
			try:
				self.p.stdin.write(self.buf[:16384])
			except IOError as e:
				if e.errno == errno.EAGAIN:
					self.iww.start()
					return
				else: self._close(EVException('Exception {0}'.format(e)))
			except Exception as e:
				self._close(EVException('Exception {0}'.format(e)))
			else:
				del self.buf[:16384]
				if len(self.buf) < 16384*2:
					self._event('writable')

		if len(self.buf)>0 and not self.iww.active:
			self.iww.start()

		self._writing = False

	def _close(self, e):
		if self.orw.active:
			self.orw.invoke(pyev.EV_READ)
			self.orw.stop()
		if self.erw.active:
			self.erw.invoke(pyev.EV_READ)
			self.erw.stop()
		self.p.stdout.close()
		self.p.stderr.close()
		self.p.stdin.close()
		self._closed = True
		self._event('close', e)

if __name__ == '__main__':
	def incoming(data):
		print 'stdout:', data
	def incominge(data):
		print 'stderr:', data

	def writeto(p):
		p.write('test test test\n')
		p.write('test test test\n')

	def killp(p):
		print 'sending TERM'
		p.p.terminate()
	def killp2(p):
		print 'sending KILL'
		p.p.kill()

	def poll(p):
		print 'poll', p.p.poll(), p.p.returncode
		later(1.0, poll, p)

	def closed(e):
		print 'subprocess closed', e
		#unloop()

	def end():
		print 'end.'
		unloop()

	def status(p):
		print 'status', p

	p = Process(['/bin/nc', '-vvn', '127.0.0.1', '50000'])
	p._on('read', incoming)
	p._on('readerr', incominge)
	p._on('close', closed)
	p.write('abcdef\n')
	#later(5.0, status, p)
	later(1.0, poll, p)

	#later(5.0, writeto, p)
	#later(5.0, killp, p)
	#later(7.0, killp, p)
	later(15.0, end)
	loop()
	print 'sys.exit'
	sys.exit(0)


