import asyncio
import os
import os.path


def prepare_argparser():
    import argparse
    import pkg_resources

    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=r"""
        ____________________________________________________________________
                                                  __
                                   /            /    )
        ------__-----__-----__----/-__----__-----___/------------_/_----)__-
            /   )  /___)  /   )  /(      (_ `  /         /   /   /     /   )
        ___/___/__(___ __(___(__/___\___(__)__/____/____(___(___(_ ___/_____
          /
         /

        Use MACS3 to build forward and reverse peaks files for given .bam
        file.
        Iterate peaks through set of criteria to determine UTR viability,
        before annotating in .gff file.
        """
    )
    parser.add_argument('GFF_IN', help="input 'canonical' annotations file in gff or gtf format.")
    parser.add_argument('BAM_IN', help="input reads file in bam format.")
    parser.add_argument('--max-distance', type=int, default=200,
                        help='maximum distance in bases that UTR can be from a transcript.')
    parser.add_argument('--override-utr', action="store_true", help="ignore already annotated 3' UTRs in criteria.")
    parser.add_argument('--extend-utr', action="store_true",
                        help="extend previously existing 3' UTR annotations where possible.")
    parser.add_argument('--five-prime-ext', type=int, default=0,
                        help='a peak within this many bases of a gene\'s 5\'-end should be assumed to belong to it.')
    parser.add_argument('--skip-soft-clip', action="store_true",
                        help="skip the resource-intensive logic to pileup soft-clipped read edges.")
    parser.add_argument('--min-pileups', type=int, default=10, help='Minimum number of piled-up mapped reads for UTR cut-off.')
    parser.add_argument('--min-poly-tail', type=int, default=10,
                        help='Minimum length of poly-A/T tail considered in soft-clipped reads.')
    parser.add_argument('-p', '--processors', type=int, default=1, help="How many processor cores to use.")
    parser.add_argument('-f', '-force', '--force', action="store_true", help="Overwrite outputs if they exist.")
    parser.add_argument('-o', '--output', help="output filename.")
    parser.add_argument('--gtf', dest="gtf_out", action="store_true", help="output in GTF format (rather than default GFF3).")
    parser.add_argument('--keep-cache', action="store_true", help="Keep cached files on run completion.")
    parser.add_argument('--version', action='version',
                        version='%(prog)s {version}'.format(version=pkg_resources.require(__package__)[0].version))
    return parser


def demo():
    """
    Entry-point for peaks2utr-demo
    """
    from glob import glob

    demo_dir = os.path.join(os.path.dirname(__file__), "demo")
    gff_in = glob(os.path.join(demo_dir, "*.gff"))[0]
    bam_in = glob(os.path.join(demo_dir, "*.bam"))[0]
    argparser = prepare_argparser()
    args = argparser.parse_args([gff_in, bam_in, "-f"])
    asyncio.run(_main(args))


def main():
    """
    Main entry-point
    """
    from psutil import virtual_memory

    from .constants import PERC_ALLOCATED_VRAM
    from .utils import limit_memory

    limit_memory(PERC_ALLOCATED_VRAM * virtual_memory().total / 100)
    argparser = prepare_argparser()
    args = argparser.parse_args()
    asyncio.run(_main(args))


async def _main(args):
    """
    The main function / pipeline for peaks2utr.
    """
    import logging
    import shutil
    import sys

    from . import constants
    from .annotations import AnnotationsPipeline
    from .collections import AnnotationsDict, BroadPeaksList
    from .utils import cached, yield_from_process
    from .preprocess import BAMSplitter, call_peaks, create_db
    from .postprocess import merge_annotations, gt_gff3_sort, write_summary_stats

    try:
        ###################
        # Setup logging   #
        ###################

        # Change root logger level from WARNING (default) to NOTSET in order for all messages to be delegated.
        logging.getLogger().setLevel(logging.NOTSET)

        # Add stdout handler, with level INFO.
        console = logging.StreamHandler(sys.stdout)
        console.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        console.setFormatter(formatter)
        logging.getLogger().addHandler(console)

        if not os.path.exists(constants.LOG_DIR):
            logging.info("Make .log directory")
            os.mkdir(constants.LOG_DIR)

        # Add file handler, with level DEBUG.
        fileHandler = logging.FileHandler(
            filename=os.path.join(constants.LOG_DIR, '{}_debug.log'.format(__package__)), mode="w")
        fileHandler.setLevel(logging.DEBUG)
        fileHandler.setFormatter(formatter)
        logging.getLogger().addHandler(fileHandler)

        ###################
        # Define outputs  #
        ###################

        if not os.path.exists(constants.CACHE_DIR):
            logging.info("Make .cache directory")
            os.mkdir(constants.CACHE_DIR)

        bam_basename = os.path.basename(os.path.splitext(args.BAM_IN)[0])
        gff_base, gff_ext = os.path.splitext(args.GFF_IN)
        gff_basename = os.path.basename(gff_base)
        args.gtf_in = True if "gtf" in gff_ext else False
        if not args.output:
            new_gff_fn = gff_basename + ".new"
            new_gff_fn += ".gtf" if args.gtf_out else ".gff3"
        else:
            new_gff_fn = args.output

        ###################
        # Perform checks  #
        ###################

        if os.path.exists(new_gff_fn) and not args.force:
            logging.error("%s already exists. Re-run with -f flag to force overwrite of output files. Aborting." % new_gff_fn)
            sys.exit(1)

        if args.override_utr and args.extend_utr:
            logging.error("Only one of --extend-utr and --override-utr can be used simultaneously. Aborting.")
            sys.exit(1)

        ###################
        # Pre-processing  #
        ###################

        BAMSplitter(bam_basename, args).process()

        db, _, _ = await asyncio.gather(
            create_db(args.GFF_IN),
            call_peaks(bam_basename, "forward"),
            call_peaks(bam_basename, "reverse")
        )
        peaks = \
            BroadPeaksList(broadpeak_fn=cached("forward_peaks.broadPeak"), strand="forward") + \
            BroadPeaksList(broadpeak_fn=cached("reverse_peaks.broadPeak"), strand="reverse")

        ###################
        # Process peaks   #
        ###################

        annotations = AnnotationsDict(args=args)
        with AnnotationsPipeline(peaks, args, db_path=db) as pipeline:
            for p in pipeline.processes:
                for result in yield_from_process(pipeline.queue, p, pipeline.pbar):
                    if result:
                        annotations.update(result)

        ###################
        # Post-processing #
        ###################

        merge_annotations(db, annotations)
        gt_gff3_sort(annotations, new_gff_fn, args.force, args.gtf_out)
        write_summary_stats(annotations, pipeline)

        logging.info("%s finished successfully." % __package__)
        await asyncio.sleep(1)
        sys.exit(0)
    except KeyboardInterrupt:
        logging.error("User interrupted processing. Aborting.")
        sys.exit(130)
    finally:
        try:
            if not args.keep_cache:
                logging.info("Clearing cache.")
                shutil.rmtree(constants.CACHE_DIR)
        except NameError:
            pass
