import multiprocessing
import os.path
from queue import Empty
import resource

import gffutils

from .constants import CACHE_DIR
from .exceptions import EXCEPTIONS_MAP


class Falsey:

    def __bool__(self):
        return False


class Counter:
    seen = set()

    def __init__(self):
        self.val = multiprocessing.Value('i', 0)
        self.lock = multiprocessing.Lock()

    def __int__(self):
        return self.value

    def add(self, key):
        """
        Add key to global seen set. This Counter will only increment if key is not a duplicate in _any_ Counter.
        """
        if key not in self.seen:
            with self.lock:
                self.val.value += 1
                self.seen.add(key)

    def increment(self):
        """
        Increment this Counter in any circumstance.
        """
        with self.lock:
            self.val.value += 1

    @property
    def value(self):
        with self.lock:
            return self.val.value


def cached(filename):
    return os.path.join(CACHE_DIR, filename)


async def consume_lines(pipe, log_file):
    """
    Asynchronously write lines in pipe to log file.
    """
    with open(log_file, 'bw') as f:
        while line := await pipe.readline():
            f.write(line)


def multiprocess_over_dict(f, d):
    """
    Assign a multiprocessing Process to call function f for every key-value pair in d, passing this item
    as the function's first argument.
    Start each process and wait for them all to finish before returning.
    """
    jobs = []
    for input, output in d.items():
        p = multiprocessing.Process(target=f, args=(input, output))
        jobs.append(p)
        p.start()
    for job in jobs:
        job.join()
        if job.exitcode != 0:
            raise EXCEPTIONS_MAP.get(f.__name__, Exception)


def format_stats_line(msg, total, numerator=None):
    """
    Format given statistics message with optional percentage.
    """
    msg += ": "
    if numerator is None:
        msg += "{}\n".format(total)
    else:
        msg += "{} ({}%)\n".format(numerator, int(100 * numerator / total))
    return msg


def iter_batches(lst, n):
    """
    Yield successive n-sized chunks from lst.
    """
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def yield_from_process(q, p, pbar=None):
    """
    Yield items in queue q while each process p is alive. This prevents program from locking up when queue
    gets too large.
    Pass an optional tqdm progress bar (pbar) to keep a single progress bar running over multiple processes.
    """
    while p.is_alive():
        p.join(timeout=1)
        while True:
            try:
                yield q.get(block=False)
                if pbar:
                    pbar.update()
            except Empty:
                break


def limit_memory(maxsize):
    """
    Limit total available memory globally to maxsize bytes. Will throw MemoryError if breached.
    """
    _, hard = resource.getrlimit(resource.RLIMIT_AS)
    resource.setrlimit(resource.RLIMIT_AS, (int(maxsize), hard))


def filter_nested_dict(node, threshold):
    """
    For an n-nested dictionary, filter out integer leaves with a minimum threashold value.
    """
    if isinstance(node, int):
        if node >= threshold:
            return node
    else:
        dupe_node = {}
        for k, v in node.items():
            cur_node = filter_nested_dict(v, threshold)
            if cur_node:
                dupe_node[k] = cur_node
        return dupe_node or None


def sum_nested_dicts(d1, d2):
    """
    For an n-nested dictionary, sum numeric values in leaves with matching keys.
    """
    def sum(v1, v2):
        if v2 is None:
            return v1
        try:
            return v1 + v2
        except TypeError:
            return sum_nested_dicts(v1, v2)
    result = d2.copy()
    result.update({k: sum(v, d2.get(k)) for k, v in d1.items()})
    return result


def feature_from_line(line, dialect_in, dialect_out):
    """
    Given a line from a GFF file, return a Feature object.
    
    This adapts gffutils.feature.feature_from_line to allow an output dialect to
    be specified, in addition to the dialect used for parsing the feature string.
    """
    fields = line.rstrip('\n\r').split('\t')
    try:
        attr_string = fields[8]
    except IndexError:
        attr_string = ""
    attrs, _ = gffutils.parser._split_keyvals(attr_string, dialect=dialect_in)
    d = dict(list(zip(gffutils.constants._gffkeys, fields)))
    d['attributes'] = attrs
    d['extra'] = fields[9:]
    d['keep_order'] = True
    return gffutils.Feature(dialect=dialect_out, **d)
