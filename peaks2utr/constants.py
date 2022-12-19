import os
import os.path


class AnnotationColour:
    artemis_colour_map = {
        "magenta": "6",
        "green": "3",
        "blue": "4",
    }
    Extended = artemis_colour_map["green"]
    ExtendedWithSPAT = artemis_colour_map["blue"]
    TruncatedZeroCoverage = artemis_colour_map["magenta"]


class FeatureTypes:
    Gene = ['gene', 'protein_coding_gene']
    FivePrimeUTR = ['five_prime_UTR', 'five_prime_utr']
    ThreePrimeUTR = ['three_prime_UTR', 'three_prime_utr']
    GtfTranscript = ['transcript']
    GffTranscript = ['mRNA']


STRAND_MAP = {
    'forward': '+',
    'reverse': '-',
}

STRAND_CIGAR_SOFT_CLIP_REGEX = {
    "forward": r"([0-9]+)S$",
    "reverse": r"^([0-9]+)S"
}

STRAND_PYSAM_ARGS = {
    'forward': ["-F", "20"],
    'reverse': ["-f", "16"],
}

GFFUTILS_GTF_DIALECT = {
    'leading semicolon': False,
    'trailing semicolon': True,
    'quoted GFF2 values': True,
    'field separator': '; ',
    'keyval separator': ' ',
    'multival separator': ',',
    'fmt': 'gtf',
    'repeated keys': False,
    'order': ['gene_id', 'transcript_id', 'ID', 'Name'],
}

GFFUTILS_GFF_DIALECT = {
    'leading semicolon': False,
    'trailing semicolon': False,
    'quoted GFF2 values': False,
    'field separator': ';',
    'keyval separator': '=',
    'multival separator': ',',
    'fmt': 'gff3',
    'repeated keys': False,
    'order': ['ID', 'Name', 'gene_id', 'transcript_id']
}

CACHE_DIR = os.path.join(os.getcwd(), '.cache')
LOG_DIR = os.path.join(os.getcwd(), '.log')

TMP_GFF_FN = "_tmp.gff"

PERC_ALLOCATED_VRAM = 75
