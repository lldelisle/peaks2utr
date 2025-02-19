import unittest
from unittest.mock import MagicMock

from peaks2utr import prepare_argparser
from peaks2utr.collections import AnnotationsDict
from peaks2utr.constants import FeatureTypes, GFFUTILS_GTF_DIALECT
from peaks2utr.models import Feature, UTR


class TestOutputFormatting(unittest.TestCase):

    def setUp(self):
        chr = "chr1"
        start = 1000
        end = 2000
        strand = "+"
        gene_id = "gene1"
        argparser = prepare_argparser()
        self.args = argparser.parse_args(["", ""])
        self.gene_gff = Feature(chr, id=gene_id, featuretype=FeatureTypes.Gene[0], start=start, end=end, strand=strand,
                                attributes={"ID": [gene_id]})
        self.transcript_gff = Feature(chr, id="gene1:mRNA", featuretype=FeatureTypes.GffTranscript[0], start=start, end=end,
                                      strand=strand, attributes={"ID": ["gene1:mRNA"], "Parent": [gene_id]})
        self.gene_gtf = Feature(chr, id=gene_id, featuretype=FeatureTypes.Gene[0], source="gffutils_derived",
                                start=start, end=end, strand=strand, attributes={"gene_id": [gene_id]},
                                dialect=GFFUTILS_GTF_DIALECT)
        self.transcript_gtf = Feature(chr, id="gene1.1", featuretype=FeatureTypes.GtfTranscript[0], start=start, end=end,
                                      strand=strand, attributes={"transcript_id": ["gene1.1"], "gene_id": [gene_id]},
                                      dialect=GFFUTILS_GTF_DIALECT)
        self.utr = UTR(start=start, end=end)
        self.db = MagicMock()
        self.db.children = MagicMock(return_value=[Feature(id="utr_1", featuretype=FeatureTypes.FivePrimeUTR[0])])

    def test_gff_to_gff(self):
        self.args.gtf_in = False
        self.args.gtf_out = False
        expected_gene = ["chr1", ".", "gene", "1000", "2000", ".", "+", ".", "ID=gene1"]
        expected_transcript = ["chr1", ".", "mRNA", "1000", "2000", ".", "+", ".", "ID=gene1:mRNA;Parent=gene1"]
        expected_utr = ["chr1", "peaks2utr", "three_prime_UTR", "1000", "2000", ".", "+", ".",
                        "ID=utr_2;Parent=gene1:mRNA;colour=3"]
        self.utr.generate_feature(self.gene_gff, self.transcript_gff, self.db, gtf_in=self.args.gtf_in)
        annotations = AnnotationsDict(args=self.args)
        annotations.update({
            self.gene_gff.id: {"gene": self.gene_gff, "transcript": self.transcript_gff, "utr": self.utr.feature}
        })
        gene, transcript, utr = annotations.iter_feature_strings()
        self.assertListEqual(gene.strip().split("\t"), expected_gene)
        self.assertListEqual(transcript.strip().split("\t"), expected_transcript)
        self.assertListEqual(utr.strip().split("\t"), expected_utr)

    def test_gff_to_gtf(self):
        self.args.gtf_in = False
        self.args.gtf_out = True
        expected_transcript = ["chr1", ".", "transcript", "1000", "2000", ".", "+", ".",
                               'gene_id "gene1"; transcript_id "gene1:mRNA";']
        expected_utr = ["chr1", "peaks2utr", "three_prime_UTR", "1000", "2000", ".", "+", ".",
                        'gene_id "gene1"; transcript_id "gene1:mRNA"; colour "3";']
        self.utr.generate_feature(self.gene_gff, self.transcript_gff, self.db, gtf_in=self.args.gtf_in)
        annotations = AnnotationsDict(args=self.args)
        annotations.update({
            self.gene_gff.id: {"gene": self.gene_gff, "transcript": self.transcript_gff, "utr": self.utr.feature}
        })
        transcript, utr = annotations.iter_feature_strings()
        self.assertListEqual(transcript.strip().split("\t"), expected_transcript)
        self.assertListEqual(utr.strip().split("\t"), expected_utr)

    def test_gtf_to_gff(self):
        self.args.gtf_in = True
        self.args.gtf_out = False
        expected_gene = ["chr1", "gffutils_derived", "gene", "1000", "2000", ".", "+", ".", "ID=gene1"]
        expected_transcript = ["chr1", ".", "mRNA", "1000", "2000", ".", "+", ".", "ID=gene1.1;Parent=gene1"]
        expected_utr = ["chr1", "peaks2utr", "three_prime_UTR", "1000", "2000", ".", "+", ".",
                        "ID=utr_2;Parent=gene1.1;colour=3"]
        self.utr.generate_feature(self.gene_gtf, self.transcript_gtf, self.db, gtf_in=self.args.gtf_in)
        annotations = AnnotationsDict(args=self.args)
        annotations.update({
            self.gene_gtf.id: {"gene": self.gene_gtf, "transcript": self.transcript_gtf, "utr": self.utr.feature}
        })
        gene, transcript, utr = annotations.iter_feature_strings()
        self.assertListEqual(gene.strip().split("\t"), expected_gene)
        self.assertListEqual(transcript.strip().split("\t"), expected_transcript)
        self.assertListEqual(utr.strip().split("\t"), expected_utr)

    def test_gtf_to_gtf(self):
        self.args.gtf_in = True
        self.args.gtf_out = True
        expected_transcript = ["chr1", ".", "transcript", "1000", "2000", ".", "+", ".",
                               'gene_id "gene1"; transcript_id "gene1.1";']
        expected_utr = ["chr1", "peaks2utr", "three_prime_UTR", "1000", "2000", ".", "+", ".",
                        'gene_id "gene1"; transcript_id "gene1.1"; colour "3";']
        self.utr.generate_feature(self.gene_gtf, self.transcript_gtf, self.db, gtf_in=self.args.gtf_in)
        annotations = AnnotationsDict(args=self.args)
        annotations.update({
            self.gene_gtf.id: {"gene": self.gene_gtf, "transcript": self.transcript_gtf, "utr": self.utr.feature}
        })
        transcript, utr = annotations.iter_feature_strings()
        self.assertListEqual(transcript.strip().split("\t"), expected_transcript)
        self.assertListEqual(utr.strip().split("\t"), expected_utr)


if __name__ == '__main__':
    unittest.main()
