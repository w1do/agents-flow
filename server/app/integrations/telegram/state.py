from collections import OrderedDict
from heapq import heappop, heappush, heapify
from itertools import count
from time import monotonic


class ExpiringCache:
    def __init__(self, ttl, limit, on_evict=None):
        self.ttl, self.limit, self.items = ttl, limit, OrderedDict()
        self.expiry, self.sequence = [], count()
        self.on_evict = on_evict

    def evict(self, key):
        item = self.items.pop(key)
        if self.on_evict:
            self.on_evict(item[1])

    def prune(self):
        now = monotonic()
        while self.expiry and self.expiry[0][0] <= now:
            expires, _, key = heappop(self.expiry)
            item = self.items.get(key)
            if item is not None and item[0] == expires:
                self.evict(key)

    def put(self, key, value, ttl=None):
        self.prune()
        self.items.pop(key, None)
        expires = monotonic() + (self.ttl if ttl is None else ttl)
        self.items[key] = (expires, value)
        heappush(self.expiry, (expires, next(self.sequence), key))
        while len(self.items) > self.limit:
            self.evict(next(iter(self.items)))
        if len(self.expiry) > 2 * self.limit:
            self.expiry = [(item[0], next(self.sequence), key) for key, item in self.items.items()]
            heapify(self.expiry)

    def get(self, key):
        self.prune()
        item = self.items.get(key)
        return item[1] if item else None

    def remove(self, key):
        self.items.pop(key, None)


class UpdateCache:
    """Single event-loop reservations; active requests never expire mid-download."""
    def __init__(self, ttl=86400, limit=10000, capacity=16):
        self.ttl, self.done, self.active = ttl, ExpiringCache(ttl, limit), set()
        self.capacity = capacity

    def acquire(self, update_id):
        if self.done.get(update_id) is not None:
            return "done"
        if update_id in self.active:
            return "busy"
        if len(self.active) >= self.capacity:
            return "full"
        self.active.add(update_id)
        return "new"

    def complete(self, update_id, ttl=None):
        self.done.put(update_id, True, ttl)

    def release(self, update_id):
        self.active.discard(update_id)


class FeedbackCache:
    def __init__(self, ttl=900, limit=2000, actions=None):
        self.actions = actions
        self.cache = ExpiringCache(ttl, limit, on_evict=self.evicted)

    def evicted(self, record):
        value, owner = record
        if self.actions and owner is not None:
            self.actions.release(value[-1], owner)

    @property
    def items(self):
        return self.cache.items

    def put(self, chat, user, prompt, task_id, kind, decision, revision=None, action=None):
        owner = self.actions.cache.get(action) if self.actions else None
        self.cache.put((chat, user, prompt), ((task_id, kind, decision, revision, action), owner))

    def get(self, chat, user, prompt):
        record = self.cache.get((chat, user, prompt))
        if record is not None:
            value, owner = record
            if self.actions is None or self.actions.cache.get(value[-1]) is owner:
                return value

    def remove(self, chat, user, prompt):
        self.cache.remove((chat, user, prompt))

    def take(self, chat, user, prompt):
        key = (chat, user, prompt)
        value = self.get(chat, user, prompt)
        if value is not None:
            self.cache.remove(key)
        return value


class ActionCache:
    def __init__(self, ttl=86400, limit=10000):
        self.cache = ExpiringCache(ttl, limit)

    def claim(self, token, ttl=None):
        if self.cache.get(token) is not None:
            return False
        self.cache.put(token, object(), ttl)
        return True

    def release(self, token, owner=None):
        if owner is None or self.cache.get(token) is owner:
            self.cache.remove(token)
