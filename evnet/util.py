
import collections
import weakref

class EventGen(object):
	def __init__(self):
		self._event_subscribers = collections.defaultdict(list)

	def _on(self, name, cb):
		#self._event_subscribers[name].append(WeakMethod(cb))
		self._event_subscribers[name].append(cb)

	def _event(self, name, *args):
		for cb in self._event_subscribers[name]:
			#if cb.alive():
				cb(*args)

# some support classes for weakly referencing methods
class WeakMethodBound:
	def __init__(self, f):
		self.f = f.im_func
		self.c = weakref.ref(f.im_self)
	def __call__(self, *args):
		if self.c() == None:
			raise TypeError, 'Method called on dead object'
		apply(self.f, (self.c(),) + args)
	def alive(self):
		return (not self.c() == None)

class WeakMethodFree:
	def __init__(self, f):
		self.f = weakref.ref(f)
	def __call__(self, *args):
		if self.f() == None:
			raise TypeError, 'Function no longer exist'
		apply(self.f(), args)
	def alive(self):
		return (not self.f() == None)

def WeakMethod(f):
	try :
		f.im_func
	except AttributeError :
		return WeakMethodFree(f)
	return WeakMethodBound(f)


