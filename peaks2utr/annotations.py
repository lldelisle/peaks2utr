import copy
import logging
import math
import multiprocessing
import sqlite3

from tqdm import tqdm

from . import constants, criteria
from .constants import AnnotationColour, STRAND_MAP
from .collections import SPATTruncationPointsDict, ZeroCoverageIntervalsDict
from .exceptions import AnnotationsError
from .models import UTR, FeatureDB
from .utils import Counter, Falsey, cached, iter_batches


class NoNearbyFeatures(Falsey):
    pass


class PotentialUTRZeroCoverage(Falsey):
    pass


class AnnotationsPipeline:
    def __init__(self, peaks, args, queue=None, db_path=None):
        super().__init__()
        self.no_features_counter = Counter()
        self.new_utr_counter = Counter()
        self.zero_coverage_removal_counter = Counter()
        self.peaks = peaks
        self.total_peaks = len(peaks)
        self.args = args
        self.queue = queue or multiprocessing.Queue()
        self.db_path = db_path

    def __enter__(self):
        if not self.db_path:
            raise AnnotationsError("Please instantiate {} with db_path kwarg.".format(self.__class__.__name__))
        self.processes = [
            self._batch_annotate_strand(batch)
            for batch in iter_batches(self.peaks, math.ceil(self.total_peaks/self.args.processors))
        ]
        for p in self.processes:
            p.start()
        self.pbar = tqdm(total=self.total_peaks, desc=f'{"INFO": <8} Iterating over peaks to annotate 3\' UTRs.')
        return self

    def __exit__(self, type, value, traceback):
        self.pbar.close()

    def _connect_db(self):
        db = sqlite3.connect(self.db_path, check_same_thread=False)
        return FeatureDB(db)

    def _batch_annotate_strand(self, peaks_batch):
        """
        Create multiprocessing Process to handle batch of peaks. Connect to sqlite3 db for each batch to prevent
        serialization issues.
        """
        truncation_points = {}
        coverage_gaps = {}
        for strand, symbol in STRAND_MAP.items():
            truncation_points[symbol] = SPATTruncationPointsDict(json_fn=cached(strand + "_unmapped.json"))
            coverage_gaps[symbol] = ZeroCoverageIntervalsDict(bed_fn=cached(strand + "_coverage_gaps.bed"))
        db = self._connect_db()
        return multiprocessing.Process(target=self._iter_peaks, args=(db, peaks_batch, truncation_points, coverage_gaps))

    def _iter_peaks(self, db, peaks_batch, truncation_points, coverage_gaps):
        for peak in peaks_batch:
            self.annotate_utr_for_peak(
                db,
                peak,
                truncation_points.get(peak.strand),
                coverage_gaps.get(peak.strand))

    def _filter_db(self, db, chr, start, end, strand, featuretype):
        features = list(db.region(
            seqid=chr,
            start=start - self.args.max_distance,
            end=end + self.args.max_distance,
            strand=strand,
            featuretype=featuretype)
        )
        return sorted(features, key=lambda x: x.start, reverse=False if strand == "+" else True)

    def annotate_utr_for_peak(self, db, peak, truncation_points, coverage_gaps):
        """
        Find genes in region of given peak and apply criteria to determine if 3' UTR exists for each.
        If so, add to multiprocessing Queue.

        Args:
            db (gffutils.interface.FeatureDB)
            truncation_points (SPATTruncationPointsDict)
            coverage_gaps (ZeroCoverageIntervalsDict)
        """
        utr_found = False
        genes = self._filter_db(db, peak.chr, peak.start, peak.end, peak.strand, constants.FeatureTypes.Gene) or []
        if genes:
            for idx, gene in enumerate(genes):
                transcripts = db.children(
                    gene,
                    featuretype=constants.FeatureTypes.GffTranscript + constants.FeatureTypes.GtfTranscript,
                    order_by="end" if peak.strand == "+" else "start",
                    reverse=True if peak.strand == "+" else False
                )
                # Take outermost transcript
                try:
                    transcript = next(transcripts)
                except StopIteration:
                    continue
                try:
                    criteria.assert_whether_utr_already_annotated(peak, transcript, db,
                                                                  self.args.override_utr, self.args.extend_utr)
                    criteria.assert_not_a_subset(peak, transcript)
                    utr = UTR(start=peak.start, end=peak.end)
                    criteria.assert_3_prime_end_and_truncate(peak, transcript, utr)
                    if len(genes) > idx + 1:
                        next_gene = copy.deepcopy(genes[idx + 1])
                        criteria.belongs_to_next_gene(peak, next_gene, self.args.five_prime_ext)
                        criteria.truncate_5_prime_end(peak, next_gene, utr, self.args.five_prime_ext)
                except criteria.CriteriaFailure as e:
                    logging.debug("%s - %s" % (type(e).__name__, e))
                else:
                    colour = AnnotationColour.Extended
                    intersect = utr.range.intersection(map(int, sorted(truncation_points[peak.chr], key=int))) \
                        if peak.chr in truncation_points else None
                    if peak.strand == "+":
                        gaps = coverage_gaps.filter(peak.chr, utr.end)
                        try:
                            gap_edge = min([g.start for g in gaps])
                        except ValueError:
                            pass
                        else:
                            utr.end = max(transcript.end, gap_edge)
                            colour = AnnotationColour.TruncatedZeroCoverage
                    else:
                        gaps = coverage_gaps.filter(peak.chr, utr.start)
                        try:
                            gap_edge = max([g.end for g in gaps])
                        except ValueError:
                            pass
                        else:
                            utr.start = min(transcript.start, gap_edge)
                            colour = AnnotationColour.TruncatedZeroCoverage
                    if intersect:
                        if peak.strand == "+":
                            utr.end = max(intersect)
                        else:
                            utr.start = min(intersect)
                        colour = AnnotationColour.ExtendedWithSPAT
                    if utr.is_valid():
                        logging.debug("Peak {} corresponds to 3' UTR {} of gene {}".upper().format(peak.name, utr, gene.id))
                        utr.generate_feature(gene, transcript, db, colour, self.args.gtf_in)
                        features = {"gene": gene, "transcript": transcript}
                        features.update({"feature_{}".format(idx): f for idx, f in enumerate(db.children(transcript))
                                        if f.id != transcript.id and f.id != gene.id})
                        features.update({"utr": utr.feature})
                        if peak.strand == "+":
                            gene.end = transcript.end = utr.end
                        else:
                            gene.start = transcript.start = utr.start
                        self.queue.put({gene.id: features})
                        utr_found = True
                        self.new_utr_counter.increment()
                    else:
                        if utr.length == 0:
                            logging.debug(
                                "Peak {} corresponds to potential 3' UTR that was removed due to zero read coverage."
                                .format(peak.name))
                            self.queue.put(PotentialUTRZeroCoverage())
                            self.zero_coverage_removal_counter.add(peak.name)
                        else:
                            logging.error(
                                "Peak {} produced abnormal 3' UTR {} for gene {}. "
                                "This is a bug, please report at https://github.com/haessar/peaks2utr/issues."
                                .format(peak.name, utr, gene.id))
        else:
            logging.debug("No features found near peak %s" % peak.name)
            self.queue.put(NoNearbyFeatures())
            self.no_features_counter.add(peak.name)
            return
        if not utr_found:
            self.queue.put(None)
