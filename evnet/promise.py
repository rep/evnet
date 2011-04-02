
import logging

from . import schedule, EVException

EVENTUAL = 1
FULFILLED = 2
BROKEN = 3

class Promise(object):
	def __init__(self):
		self.__state = EVENTUAL
		self._callbacks = []
		self._errbacks = []
		self._calls = []
		self._result = None

	def _state(self):
		return self.__state

	def _call_errbacks(self):
		if self.__state == BROKEN:
			for fn, args, kwargs in self._errbacks:
				#schedule(fn, self._result, *args, **kwargs)
				fn(self._result, *args, **kwargs)
			self._errbacks = []

	def _call_callbacks(self):
		if self.__state == FULFILLED:
			# call all callbacks and invoke all methods
			for fn, args, kwargs in self._callbacks:
				#schedule(fn, self._result, *args, **kwargs)
				fn(self._result, *args, **kwargs)
			self._callbacks = []

			for p, m, args, kwargs in self._calls:
				self._exec_call(p, m, args, kwargs)
			self._calls = []

	def _exec_call(self, p, m, args, kwargs):
		f = getattr(self._result, m)
		#r = f(*args, **kwargs)
		#p._resolve(r)
		#return
		def tmpcaller():
			r = f(*args, **kwargs)
			p._resolve(r)
		schedule(tmpcaller)

	def _chain(self, cbs, calls, ebs):
		self._callbacks += cbs
		self._calls += calls
		self._errbacks += ebs
		self._call_callbacks()
		self._call_errbacks()

	def _resolve(self, result):
		if self.__state != EVENTUAL:
			raise EVException('Promises may only be fulfilled once.')

		self.__state = FULFILLED
		self._result = result

		if isinstance(result, Promise):
			result._chain(self._callbacks, self._calls, self._errbacks)
			self._when = result._when
			self._except = result._except
			self._state = result._state
			self._call = result._call
			self._chain = result._chain
			self.__getattr__ = result.__getattr__
		else:
			self._call_callbacks()

	def _smash(self, exc):
		if self.__state == BROKEN:
			raise EVException('Promises may only be broken once.')
		if self.__state == FULFILLED:
			raise EVException('Promise was fulfilled and now broken?')
		self._result = exc
		self.__state = BROKEN
		# now call all errbacks, ignoring method calls
		if not self._errbacks:
			logging.warn('Promise without errbacks smashed with exception: {0}'.format(exc))
		self._call_errbacks()
		
	def _when(self, cb, *args, **kwargs):
		if self.__state == EVENTUAL:
			self._callbacks.append((cb, args, kwargs))
		elif self.__state == FULFILLED:
			#schedule(cb, self._result, *args, **kwargs)
			cb(self._result, *args, **kwargs)

	def _except(self, cb, *args, **kwargs):
		if self.__state == EVENTUAL:
			self._errbacks.append((cb, args, kwargs))
		elif self.__state == BROKEN:
			#schedule(cb, self._result, *args, **kwargs)
			cb(self._result, *args, **kwargs)

	def _call(self, method, *args, **kwargs):
		p = Promise()
		if self.__state == EVENTUAL:
			self._calls.append((p, method, args, kwargs))
		elif self.__state == BROKEN:
			p._smash(self._result)
		else:
			self._exec_call(p, method, args, kwargs)
		return p

	def __getattr__(self, name):
		#logging.debug('promise __getattr__: {0}'.format(name))
		def promisingFunc(*args, **kwargs):
			return self._call(name, *args, **kwargs)
		return promisingFunc


