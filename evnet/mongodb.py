
import sys
import logging
import random
import struct
logging.basicConfig(level=logging.DEBUG)

from . import PlainClientConnection, loop, unloop, EventGen
from .promise import Promise

import bson
__binzero = '\0'*4

# some code influenced by pymongo, but a little more compact

def mongo_addhdr(op, data):
	reqid = random.randint(-2**31-1, 2**31)
	return (reqid, struct.pack('<iiii', 16+len(data), reqid, 0, op) + data)

def mongo_gen_query(options, collection, skip, num, query, fields=None):
	return mongo_addhdr(2004,
		struct.pack('<I', options) + 
		bson._make_c_string(collection) + 
		struct.pack("<ii", skip, num) +
		bson.BSON.encode(query) +
		(fields and bson.BSON.encode(fields) or '')
	)

def mongo_gen_more(collection, num, cursorid):
	return mongo_addhdr(2005, __binzero +
		bson._make_c_string(collection) +
		struct.pack('<iq', num, cursorid)
	)

def mongo_gen_insert(collection, docs, check_keys=True):
	return mongo_addhdr(2002, __binzero +
		bson._make_c_string(collection) +
		''.join([bson.BSON.encode(doc, check_keys) for doc in docs])
	)[1]

def mongo_gen_delete(collection, spec):
	return mongo_addhdr(2006, __binzero +
		bson._make_c_string(collection) +
		__binzero +
		bson.BSON.encode(spec)
	)[1]

def mongo_gen_update(collection, spec, doc, upsert=False, multi=False):
	return mongo_addhdr(2001, __binzero +
		bson._make_c_string(collection) +
		struct.pack('<i', (upsert and 1 or 0)|(multi and 2 or 0) ) + 
		bson.BSON.encode(spec) + 
		bson.BSON.encode(doc)
	)[1]


class MongoUnpack(object):
	def __init__(self):
		self.buf = bytearray()
	def __iter__(self):
		return self
	def next(self):
		return self.unpack()
	def feed(self, data):
		self.buf.extend(data)
	def unpack(self):
		if len(self.buf) < 16:
			raise StopIteration('No message.')

		ml, msgid, reqid, opcode = struct.unpack('<iiii', buffer(self.buf,0,16))
		if len(self.buf) < ml:
			raise StopIteration('No message.')
		
		rflags, cursid, start, num = struct.unpack('<iqii', buffer(self.buf,16,20))
		docs = bson.decode_all(str(buffer(self.buf, 16+20, ml-16-20)))
		del self.buf[:ml]
		return reqid, rflags, cursid, start, num, docs

class MongoConn(EventGen):
	def __init__(self, host, port):
		EventGen.__init__(self)

		self.c = PlainClientConnection((host, port))
		self.c._on('ready', self.ready)
		self.c._on('close', self.closed)
		self.c._on('read', self.read)
		self.mu = MongoUnpack()
		self.pqs = {}

	def ready(self):
		self._event('ready')

	def closed(self, e):
		self._event('close', e)

	def read(self, d):
		self.mu.feed(d)
		for reqid, rflags, cursid, start, num, docs in self.mu:
			if not reqid in self.pqs:
				logging.critical('reply with unknown request id :(')
			else:
				p, collection, buf = self.pqs.pop(reqid)
				if rflags & 1:
					p._smash(docs[0])
				else:
					buf += docs
					if cursid:
						# send getmore
						newreqid, data = mongo_gen_more(collection, num, cursid)
						self.c.write(data)
						self.pqs[newreqid] = (p, collection, buf)
					else:
						p._resolve(buf)


	def command(self, db, cmd, value=1, **kwargs):
		p = Promise()
		cmdson = bson.SON([(cmd, value)])
		cmdson.update(kwargs)
		reqid = self._sonquery('{0}.$cmd'.format(db), cmdson, limit=-1)
		self.pqs[reqid] = (p, '{0}.$cmd'.format(db), [])
		return p

	def query(self, coll, q, limit=-1):
		p = Promise()
		reqid = self._sonquery(coll, bson.SON({'$query': q}), limit=limit)
		self.pqs[reqid] = (p, coll, [])
		return p
		
	def _sonquery(self, coll, son, options=0, skip=0, limit=0, fields=None):
		reqid, data = mongo_gen_query(options, coll, skip, limit, son, fields)
		self.c.write(data)
		return reqid

	def insert(self, coll, docs):
		self.c.write(mongo_gen_insert(coll, docs))

	def delete(self, coll, spec):
		self.c.write(mongo_gen_delete(coll, spec))
		
	def update(self, coll, spec, doc, upsert=False, multi=False):
		self.c.write(mongo_gen_update(coll, spec, doc, upsert, multi))


if __name__ == '__main__':
	a = MongoConn(sys.argv[1], int(sys.argv[2]))

	def onready():
		def dbgprint(r):
			print 'dbgprint'
			for i in r:
				print 'doc', i

		p = a.query('dashboard.containers', {}, limit=2)
		p._when(dbgprint)
		p._except(dbgprint)

		if False:
			a.delete('dashboard.containers', {u'content': u'content0'})
			p = a.command('admin', 'getlasterror')
			p._when(dbgprint)
			a.insert('dashboard.containers', [{'content': 'fooinsert'},])
			p = a.command('admin', 'getlasterror')
			p._when(dbgprint)
			#a.delete('dashboard.containers', {u'content': u'fooinsert'})
			a.update('dashboard.containers', {u'content': u'fooinsert'}, {'$set': {'title':'larl'}})
			p = a.command('admin', 'getlasterror')
			p._when(dbgprint)
			for i in range(10000):
				a.insert('dashboard.containers', [{'content': 'mass '+ str(i), 'title':'massinsert'},])
			p = a.command('admin', 'getlasterror')
			p._when(dbgprint)
		
	def closed(e):
		print e
		unloop()

	a._on('ready', onready)
	a._on('close', closed)
	

	loop()


