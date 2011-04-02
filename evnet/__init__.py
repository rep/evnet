
import traceback
import signal
import socket
import logging
import errno
import threading
import Queue

import pyev
from OpenSSL import SSL

from util import EventGen, WeakMethod

default_loop = pyev.default_loop()
shutdown_callbacks = set()
scheduled_calls = []
timed_calls = set()
try:
	hints = set([ip for ip in socket.gethostbyname_ex(socket.gethostname())[2] if not ip.startswith("127.")])
except:
	hints = set()

class EVException(Exception):
	"""Eventloop Exceptions"""

def shutdown_callback(cb):
	shutdown_callbacks.add(WeakMethod(cb))

def _sigint_cb(watcher, events):
	for cb in shutdown_callbacks:
		if cb.alive():
			cb()

	watcher.loop.unloop()

def hint(sock):
	ip = sock.getsockname()[0]
	if not ip.startswith("127."):
		hints.add(ip)

def loop():
	sigint_watcher = pyev.Signal(signal.SIGINT, default_loop, _sigint_cb)
	sigint_watcher.start()
	
	default_loop.loop()

def unloop():
	for cb in shutdown_callbacks:
		if cb.alive():
			cb()

	default_loop.unloop()

def connectssl(host, port, cert='cert2.pem'):
	return ClientConnection((host,port), cert=cert)

def connectplain(host, port):
	return PlainClientConnection((host,port))

def listensock(host='', port=0, backlog_limit=5):
	sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
	sock.bind((host, port))
	sock.listen(backlog_limit)
	return sock

def listenssl(host='', port=0, backlog_limit=5, cert='cert.pem'):
	sock = listensock(host, port, backlog_limit)
	l = ListenerSSL(sock, cert=cert)
	return l

def listenplain(host='', port=0, backlog_limit=5):
	sock = listensock(host, port, backlog_limit)
	l = ListenerPlain(sock)
	return l

def schedule(cb, *args, **kwargs):
	scheduled_calls.append((cb, args, kwargs))
	schedule_timer.start()

def schedule_cb(w, e):
	l = len(scheduled_calls)
	c = 0
	for cb, args, kwargs in scheduled_calls:
		try:
			cb(*args, **kwargs)
		except:
			traceback.print_exc()
		c += 1
		if c == l:
			break
	del scheduled_calls[:c]

schedule_timer = pyev.Timer(0.0, 0.0, default_loop, schedule_cb, data=None)

def later(seconds, cb, *args, **kwargs):
	def wrap(watcher, events):
		args, kwargs = watcher.data
		timed_calls.remove(watcher)
		try:
			cb(*args, **kwargs)
		except:
			traceback.print_exc()

	t = pyev.Timer(seconds, 0.0, default_loop, wrap, data=(args, kwargs))
	timed_calls.add(t)
	t.start()


class Listener(EventGen):
	def __init__(self, sock):
		EventGen.__init__(self)
		self.sock = sock
		self.sock.setblocking(False)
		self.read_watcher = pyev.Io(self.sock, pyev.EV_READ, default_loop, self._readable)
		self.read_watcher.start()

	def _readable(self, watcher, events):
		try:
			sock, addr = self.sock.accept()
			c = self.connclass(sock, addr)
			self._event('connection', c, addr)
		except IOError as e:
			print 'ERROR', e
			self.read_watcher.stop()
			self.sock.close()
			self._event('close', self)

	def connclass(self, sock, addr):
		raise Exception('Override this!')

	def close(self):
		if self.read_watcher.active:
			self.read_watcher.stop()
		self.sock.close()
		self._event('close', self)


class ListenerPlain(Listener):
	def connclass(self, sock, addr):
		return PlainServerConnection(addr, sock)


class ListenerSSL(Listener):
	def __init__(self, sock, cert):
		self.cert = cert
		Listener.__init__(self, sock)

	def connclass(self, sock, addr):
		return ServerConnection(addr, sock, cert=self.cert)


# helper class for ssl style buffer requirements when writes fail
class SSLbuf(object):
	def __init__(self):
		self.fail = None
		self.buf = bytearray()
		self.tmp = None
		self.size = 0

	def put(self, data):
		self.buf.extend(data)
		self.size += len(data)
		#print 'put, len(data)', len(data), self.size

	def get(self):
		#print 'get, len(buf)', len(self.buf), self.fail and len(self.fail) or 'no fail'
		if self.fail:
			return self.fail
		self.tmp = buffer(self.buf, 0)
		return self.tmp

	def failed(self):
		self.fail, self.buf = self.tmp, bytearray()

	# this must be called on successful write
	def success(self, length):
		#print 'success, length', length
		self.size -= length
		if self.fail:
			self.buf, self.fail = bytearray(self.fail[length:])+self.buf, None
		else:
			del self.buf[:length]

	def __len__(self):
		return self.size
	

class Connection(EventGen):
	def __init__(self, addr, sock=None, cert=None):
		EventGen.__init__(self)
		if not sock:
			self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		else:
			self.sock = sock
		self.sock.setblocking(False)
		#self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
		self.addr = addr
		self.cert = cert

		self.sslsock = None
		self.ctx = None
		self.buf = SSLbuf()
		self._closed = False
		self._writing = False
		self.peerfp = None
		self.readbytes = 0
		self.writebytes = 0

		self.write_watcher = pyev.Io(self.sock, pyev.EV_WRITE, default_loop, self._writable)
		self.read_watcher = pyev.Io(self.sock, pyev.EV_READ, default_loop, self._readable)
		self.write_readwatcher = pyev.Io(self.sock, pyev.EV_READ, default_loop, self._writable)
		self.read_writewatcher = pyev.Io(self.sock, pyev.EV_WRITE, default_loop, self._readable)

		#self.ssl_shake()
		self.initiate()

	def initiate(self):
		raise EVException('Use subclass of Connection!')
	def set_ssl_state(self):
		raise EVException('Use subclass of Connection!')

	def _connected(self, watcher=None, events=None):
		self.write_watcher.stop()
		self.write_watcher.callback = self._writable
		serr = self.sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
		if serr == 0:
			hint(self.sock)
			self.ctx = SSL.Context(SSL.SSLv23_METHOD)
			self.ctx.use_privatekey_file(self.cert)
			self.ctx.use_certificate_file(self.cert)
			self.ctx.set_verify(SSL.VERIFY_PEER, self.verify_cb)
			self.sslsock = SSL.Connection(self.ctx, self.sock)
			self.sslsock.setblocking(False)
			self.set_ssl_state()
			self._sslshake()
		else:
			self._close('SO_ERROR: {0}'.format(errno.errorcode[serr]))

	def verify_cb(self, ok, store, *args, **kwargs):
		for cb in self._event_subscribers['verify']:
			if not cb(ok, store, *args, **kwargs):
				return 0
		return 1

	def _sslshake(self, watcher=None, events=None):
		try:
			self.sslsock.do_handshake()
		except SSL.WantWriteError:
			self.write_watcher.callback = self._sslshake
			self.write_watcher.start()
		except SSL.WantReadError:
			self.write_readwatcher.callback = self._sslshake
			self.write_readwatcher.start()
		except SSL.ZeroReturnError:
			self._close(EVException('Connection closed (ZeroReturn).'))
		except SSL.Error as e:
			self._close(EVException('SSLError {0}'.format(e)))
		else:
			self.write_readwatcher.callback = self._writable
			self.write_watcher.callback = self._writable
			pc = self.sslsock.get_peer_certificate()
			self.peerfp = pc.digest('sha1').replace(':', '').lower()
			self.read_watcher.start()
			self._event('ready')

	def stop(self):
		if self._closed:
			raise EVException('Already closed.')

		if self.read_watcher.active: self.read_watcher.stop()
		if self.write_watcher.active: self.write_watcher.stop()
		if self.read_writewatcher.active: self.read_writewatcher.stop()
		if self.write_readwatcher.active: self.write_readwatcher.stop()

	def write(self, data):
		if self._closed:
			raise EVException('Already closed.')

		if not isinstance(data, bytes):
			data = bytes(data)

		self.buf.put(data)
		self.writebytes += len(data)

		if not self.write_watcher.active and not self._writing:
			self._writeloop()

	def _writable(self, watcher, events):
		if self.write_readwatcher.active:
			self.write_readwatcher.stop()
		if self.write_watcher.active:
			self.write_watcher.stop()

		try:
			self._writeloop()
		except:
			traceback.print_exc()
			self._close(EVException('DEBUGWRAP'))

	def _writeloop(self):
		self._writing = True
		count = 0
		while not self._closed and len(self.buf) and count < 5:
			count += 1
			data = self.buf.get()
			try:
				ret = self.sslsock.send(data)
			except SSL.WantWriteError:
				self.buf.failed()
				self.write_watcher.start()
				return
			except SSL.WantReadError:
				self.buf.failed()
				self.write_readwatcher.start()
				return
			except SSL.ZeroReturnError:
				self._close(EVException('Connection closed (ZeroReturn).'))
			except SSL.Error as e:
				self._close(EVException('SSLError {0}'.format(e)))
			except Exception as e:
				self._close(EVException('Exception {0}'.format(e)))
			else:
				self.buf.success(ret)
				if len(self.buf) < 16384*2:
					self._event('writable')

		if len(self.buf) and not self.write_watcher.active:
			self.write_watcher.start()

		self._writing = False


	def _readable(self, watcher, events):
		if self.read_writewatcher.active:
			self.read_writewatcher.stop()
			self.read_watcher.start()

		count = 0
		while not self._closed and count < 5:
			count += 1
			try:
				data = self.sslsock.recv(16384)
			except SSL.WantWriteError:
				self.read_writewatcher.start()
				self.read_watcher.stop()
				break
			except SSL.WantReadError:
				break
			except SSL.ZeroReturnError:
				self._close(EVException('Connection closed (ZeroReturn).'))
			except SSL.Error as e:
				self._close(EVException('SSLError {0}'.format(e)))

			else:
				if not data:
					self._close(EVException('Connection closed. not data'))
				elif len(data) == 0:
					self._close(EVException('Connection closed. len data = 0'))
				else:
					self.readbytes += len(data)
					try:
						self._event('read', data)
					except:
						traceback.print_exc()

	def _close(self, e):
		self.stop()
		try:
			if self.sslsock: self.sslsock.shutdown()
		except:
			pass
		self.sock.close()
		self._closed = True
		self._event('close', e)

	def close(self):
		self._close(EVException('Connection closed.'))


class ClientConnection(Connection):
	def set_ssl_state(self):
		self.sslsock.set_connect_state()

	def initiate(self):
		eno = self.sock.connect_ex(self.addr)
		if eno == errno.EINPROGRESS:
			self.write_watcher.callback = self._connected
			self.write_watcher.start()
		else:
			logging.critical('socket.error != EINPROGRESS: {0}'.format(eno))
			self._close('Exception.')


class ServerConnection(Connection):
	def set_ssl_state(self):
		self.sslsock.set_accept_state()

	def initiate(self):
		self._connected()


class PlainConnection(EventGen):
	def __init__(self, addr, sock=None):
		EventGen.__init__(self)
		if not sock:
			self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		else:
			self.sock = sock
		self.sock.setblocking(False)
		#self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
		self.addr = addr

		self.buf = bytearray()
		self._closed = False
		self._writing = False

		self.write_watcher = pyev.Io(self.sock, pyev.EV_WRITE, default_loop, self._writable)
		self.read_watcher = pyev.Io(self.sock, pyev.EV_READ, default_loop, self._readable)

		self.initiate()

	def initiate(self):
		raise EVException('Use subclass of Connection!')

	def _connected(self, watcher=None, events=None):
		self.write_watcher.stop()
		self.write_watcher.callback = self._writable
		serr = self.sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
		if serr == 0:
			hint(self.sock)
			self.read_watcher.start()
			self._event('ready')
		else:
			self._close('SO_ERROR: {0}'.format(errno.errorcode[serr]))

	def stop(self):
		if self._closed:
			raise EVException('Already closed.')

		if self.read_watcher.active: self.read_watcher.stop()
		if self.write_watcher.active: self.write_watcher.stop()

	def write(self, data):
		if self._closed:
			raise EVException('Already closed.')

		if not isinstance(data, bytes):
			data = bytes(data)

		self.buf.extend(data)

		if not self.write_watcher.active and not self._writing:
			self._writeloop()

	def _writable(self, watcher, events):
		self.write_watcher.stop()

		try:
			self._writeloop()
		except:
			traceback.print_exc()
			self._close(EVException('DEBUGWRAP'))

	def _writeloop(self):
		self._writing = True
		while not self._closed and len(self.buf):
			try:
				ret = self.sock.send(self.buf)
			except socket.error as e:
				if e.errno == errno.EAGAIN:
					self.write_watcher.start()
					return
				else:
					self._close(EVException('Exception {0}'.format(e)))
			except Exception as e:
				self._close(EVException('Exception {0}'.format(e)))
			else:
				del self.buf[:ret]
				if len(self.buf) < 16384*2:
					self._event('writable')

		self._writing = False

	def _readable(self, watcher, events):
		count = 0
		while not self._closed and count < 5:
			count += 1
			try:
				data = self.sock.recv(16384)
			except socket.error as e:
				if e.errno == errno.EAGAIN:
					return
				else:
					self._close(EVException('Exception {0}'.format(e)))
			except Exception as e:
				self._close(EVException('Exception {0}'.format(e)))
			else:
				if not data:
					self._close(EVException('Connection closed. not data'))
				elif len(data) == 0:
					self._close(EVException('Connection closed. len data = 0'))
				else:
					try:
						self._event('read', data)
					except:
						traceback.print_exc()
			

	def _close(self, e):
		self.stop()
		self.sock.close()
		self._closed = True
		self._event('close', e)

	def close(self):
		self._close(EVException('Connection closed.'))


class PlainClientConnection(PlainConnection):
	def initiate(self):
		eno = self.sock.connect_ex(self.addr)
		if eno == errno.EINPROGRESS:
			self.write_watcher.callback = self._connected
			self.write_watcher.start()
		else:
			logging.critical('socket.error != EINPROGRESS: {0}'.format(eno))
			self._close('Exception.')


class PlainServerConnection(PlainConnection):
	def initiate(self):
		self._connected()


class pyevThread(threading.Thread):
	def __init__(self):
		threading.Thread.__init__(self)
		self.aw = pyev.Async(default_loop, self.process)
		self.aw.start()
		self.calls = []

	def run(self):
		default_loop.loop()

	def process(self, w, e):
		l = len(self.calls)
		c = 0
		for f, args, kwargs in self.calls:
			try:
				f(*args, **kwargs)
			except:
				traceback.print_exc()
			c += 1
			if c == l:
				break
		del self.calls[:c]
		if self.calls:
			schedule(self.process, w, e)

	def blockingCall(self, f, *a, **kw):
		q = Queue.Queue()
		def tmpcaller():
			r = f(*a, **kw)
			r._when(q.put)
			r._except(q.put)
		self.calls.append((tmpcaller, [], {}))
		self.aw.send()
		r = q.get()
		return r
