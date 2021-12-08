import os
import os.path


STRAND_MAP = {
    'forward': '+',
    'reverse': '-',
}

PYSAM_STRAND_ARGS = {
    'forward': ["-F", "20"],
    'reverse': ["-f", "16"],
}

CACHE_DIR = os.path.join(os.getcwd(), '.cache')
LOG_DIR = os.path.join(os.getcwd(), '.log')

TMP_GFF_FN = "_tmp.gff"
THREE_PRIME_UTR_GFF_FN = "three_prime_UTRs.gff"
