#!/usr/bin/env python
#
# Based on report_len_###.py developed for an in-silico PCR
# primer evaluation project Sep 2023 to Jan 2024.
import argparse
import sys
from statistics import median

if "-v" in sys.argv or "--version" in sys.argv:
    print("v1.0.0")
    sys.exit(0)

usage = """\
Produces tables with PCR primer pairs as columns, and taxonmic
lineages as rows, reporting predicted in-silico amplification.
The tables cover number of references giving an amplicon (note
a reference might give multiple amplicons), this count as a
fraction of the number of references, and the length range of
the amplicons (taking the shortest amplicon from each reference
if there is more than one).

Inputs:

* Primer definitions in 3-column TSV format used by isPcr
* Tally file from ``isPcr_tally.py`` script where the sequence
  descriptions in column 2 are taxonomic lineages

Outputs:

* Two plain text TSV files covering:
  - Counts (with reference counts as first row)
  - Median length (of shortest amplicon in each reference,
    not including the primers themselves)
* Optional Excel file with multiple sheets matching the TSV
  files plus counts as a percentage, and the length range (of
  the shortest amplicon in each reference).
* Optional heatmap as PDF file.

Example usage::

    $ sort primers.tsv | uniq | ./iupac_isPcr.py > expanded.tsv
    $ isPcr refs.fasta expanded.tsv stdout -out=bed \\
      | cut -f 1-4,6 | sort | uniq > amplicons.tsv
    $ ./isPcr_tally.py -f refs.fasta \\
      -p primers.tsv -a amplicons.tsv -o tally.tsv
    $ ./isPcr_lineage_report.py -t tally.tsv \\
      -p primers.tsv -o report -r Mammalia -l 2

Here ``primers.tsv`` is a three-column input TSV file of primer
pair name, forward, and reverse sequences -- possibly ambiguous.
Intermediate file ``expanded.tsv`` is the expanded file of
unambiguous primers, ``amplicons.tsv`` is the isPcr output in BED
format (without column 5, score), sorted and deduplicated, and
``tally.tsv`` summarises those PCR results by primer vs lineage.
Finally ``report`` is a filename stem giving ``report.xlsx`` and
``report_*.tsv`` files.

This was written for use with whole mitochondrian genomes (mtDNA),
with one representative per species. i.e. One FASTA sequence for
each species. Reporting on contigs or chromosomes like this does
not make as much sense, but it would work on sets of plasmids, or
whole bacterial genomes etc.
"""

parser = argparse.ArgumentParser(
    prog="isPcr_by_lineage.py",
    description="Produce tables of Jim Kent's isPcr results vs lineage.",
    epilog=usage,
    formatter_class=argparse.RawDescriptionHelpFormatter,
)
parser.add_argument(
    "-t",
    "--tally",
    metavar="TSV",
    required=True,
    help="PCR lengths by lineage vs primer.",
)
parser.add_argument(
    "-p",
    "--primers",
    nargs="+",
    metavar="TSV",
    required=True,
    help=(
        "Primer as isPcr style 3-column plain text TSV file(s) "
        "listing the primers in the order to report on (which "
        "can be a subset of those in the tally file)."
    ),
)
parser.add_argument(
    "--targets",
    nargs="+",
    metavar="TSV",
    help=(
        "Primer targets as 2-column plain text TSV file(s) "
        "listing target (tab) primer pair name."
    ),
)
parser.add_argument(
    "-o",
    "--output",
    metavar="STEM",
    required=True,
    help="Filename stem for reports (STEM.xlsx, STEM.pdf, and STEM_*.tsv).",
)
parser.add_argument(
    "-r",
    "--root",
    metavar="TERM",
    required=True,
    help="Taxonomic entry like 'Eukaryota', or 'Insecta'.",
)
parser.add_argument(
    "-l",
    "--levels",
    metavar="TERM",
    type=int,
    default=3,
    help="Number of taxonomic lineage levels to report on under root. Default 3.",
)
parser.add_argument(
    "-c",
    "--clump",
    nargs="+",
    metavar="LINEAGE",
    help=(
        "Optional lineages under root to clump (pool). e.g. 'Monotremata' "
        "and/or 'Eutheria;Afrotheria' under root 'Mammalia'."
    ),
)
parser.add_argument(
    "--hide",
    nargs="+",
    metavar="LINEAGE",
    help=(
        "Optional lineages entries under root to hide. e.g. under "
        "root 'Eukaryota' if hide 'Fungi incertae sedis' then "
        "'Fungi;Fungi incertae sedis;Cryptomycota' would be reported "
        "as just 'Fungi;Cryptomycota'."
    ),
)
parser.add_argument(
    "--excel",
    action="store_true",
    help="Excel output too. Requires xlsxwriter Python library.",
)
parser.add_argument(
    "--plot",
    action="store_true",
    help="Plot it too. Requires pandas and seaborn Python libraries.",
)
parser.add_argument(
    "--min-refs",
    metavar="COUNT",
    type=int,
    default=1,
    help="Minimum number of entries to display a taxonomic lineage, default 1.",
)
parser.add_argument(
    "--uniques",
    action="store_true",
    help="Extract the expected amplicon (after primer trimming) and "
    "report on the number of unique markers within each lineage entry. "
    "WARNING: Requires indexing and loading the FASTA files",
)
args = parser.parse_args()

BORDER_STYLE = 2
BORDER_COLOR = "#000000"  # black

# TODO - set at command line:
synonyms = {"Holometabola": "Endopterygota"}

primer_files = args.primers
target_files = args.targets
tally_file = args.tally
excel_file = args.output + ".xlsx"


def load_primers(primer_files):
    primers = {}
    for primer_file in primer_files:
        # sys.stderr.write(f"DEBUG: Loading primer TSV file {primer_file}\n")
        for line in open(primer_file):
            if line.startswith("#") or not line.strip():
                continue
            name, fwd, rev = line.rstrip().split("\t")[:3]
            if name not in primers:
                primers[name] = {(fwd, rev)}
            elif (fwd, rev) not in primers[name]:
                primers[name].add((fwd, rev))
            else:
                sys.stderr.write(f"WARNING - duplicate line for {name}\n")
    for name in primers:
        if (count := len(primers[name])) > 1:
            sys.stderr.write(f"WARNING - cocktail of {count} pairs for {name}\n")
    return primers


primer_defs = load_primers(primer_files)
sys.stderr.write(f"Loaded {len(primer_defs)} primers\n")


def load_primer_targets(target_files, primer_defs):
    targets = {}
    if not target_files:
        return {}
    for tsv_filename in target_files:
        for line in open(tsv_filename):
            if line.startswith("#") or not line.strip():
                continue
            a, b = line.rstrip().split("\t")
            if a not in primer_defs and b not in primer_defs:
                sys.exit(
                    f"ERROR - Entry in {tsv_filename} is not a known primer: {line}\n"
                )
            elif a != b and a in primer_defs and b in primer_defs:
                sys.exit(f"ERROR - Ambiguous naming in {tsv_filename}: {line}\n")
            elif a in primer_defs:
                targets[a] = b
            else:
                assert b in primer_defs
                targets[b] = a
    return targets


primer_targets = load_primer_targets(target_files, primer_defs)
if primer_targets:
    sys.stderr.write(f"Loaded targets for {len(primer_targets)} primers\n")

with open(tally_file) as handle:
    header = handle.readline().rstrip("\n").split("\t")
    assert header[0] == "#Sequence", header
    assert header[1] == "Description", header
    primers = {name: header.index(name) for name in primer_defs}
    mito_counts = {}  # key on lineage
    primer_counts = {}  # key on lineage, primer name
    multi_products = 0
    for line in handle:
        fields = line.rstrip("\n").split("\t")
        lineage = fields[1]  # description
        if all("0" == _ for _ in fields[2:]):
            sys.stderr.write(f"WARNING - No amplicons from {lineage}\n")
            continue  # debug!
        terms = lineage.split(";")
        if args.root not in terms:
            continue
        # Cut the lineage before requested root
        terms = terms[terms.index(args.root) + 1 :]
        if args.hide:
            for ignore in args.hide:
                if ignore in terms:
                    terms.remove(ignore)
        lineage = ";".join(terms)
        del terms
        try:
            mito_counts[lineage] += 1
        except KeyError:
            mito_counts[lineage] = 1
        # Note counting multiple amplicons per mtDNA here!
        if any(";" in _ for _ in fields[2:]):
            multi_products += 1
            # sys.stderr.write(f"WARNING - Multiple products in {lineage}\n")
        for name in primer_defs:
            value = fields[primers[name]]
            if value:
                # Take lowest length only
                value = sorted(int(_) for _ in value.split(";"))[0]
            else:
                value = 0
            assert (lineage, name) not in primer_counts, (lineage, name)
            primer_counts[lineage, name] = value
    print(
        f"Loaded product lengths for {len(mito_counts)} lineages vs {len(primers)} primers"
    )
    if multi_products:
        sys.stderr.write(
            f"WARNING - {multi_products} sequences under {args.root} with multiple products\n"
        )
    del primers


def report_group(
    count_tsv_filename,
    median_tsv_filename,
    workbook,
    root,
    levels,
    clumps=None,
    plot=None,
    min_refs=1,
):
    local_mito = {}
    local_lengths = {}
    truncations = {}
    for lineage in mito_counts:
        assert mito_counts[lineage] > 0, f"{lineage} mtDNA count {mito_counts[lineage]}"
        terms = lineage.split(";")[:levels]
        if " " in terms[-1]:
            # Drop any trailing species (these are sometimes at
            # above genus level when placement is unclear)
            # e.g. Enicocephalidae;Stenopirates;Stenopirates sp. HL-2011
            terms = terms[:-1]
        # if not terms:
        #    sys.stderr.write(
        #        f"WARNING - For {root} ignoring {lineage} {mito_counts[lineage]}\n"
        #    )
        #    continue
        cut_lineage = ";".join(terms)
        if clumps:
            for clump in clumps:
                if cut_lineage.startswith(clump + ";"):
                    # sys.stderr.write(f"DEBUG: {cut_lineage} -> {clump}\n")
                    cut_lineage = clump
        assert f"{root};" not in cut_lineage, f"{lineage} --> {cut_lineage}"
        assert mito_counts[lineage] == 1, lineage
        try:
            local_mito[cut_lineage] += mito_counts[lineage]
        except KeyError:
            local_mito[cut_lineage] = mito_counts[lineage]
        truncations[lineage] = cut_lineage

    if min_refs > 1:
        sys.stderr.write(
            f"Potentially reporting on {sum(local_mito.values())} mtDNA under {len(local_mito)} lineages under {root}\n"
        )
        # Cull lineages without enough mtDNA to display
        total = sum(local_mito.values())
        # while min(local_mito.values()) < min_refs:
        while min(v for k, v in local_mito.items() if k != "") < min_refs:
            # Sorting to do A;B;C before A;B
            for cut_lineage in sorted(local_mito, reverse=True):
                if cut_lineage and local_mito[cut_lineage] < min_refs:
                    culled = local_mito[cut_lineage]
                    del local_mito[cut_lineage]
                    more_cut = ";".join(cut_lineage.split(";")[:-1])
                    truncations[cut_lineage] = more_cut
                    try:
                        local_mito[more_cut] += culled
                    except KeyError:
                        local_mito[more_cut] = culled
                    assert cut_lineage not in local_mito
                    assert (
                        sum(local_mito.values()) == total
                    ), "Oops - culling changed the total"
                    # sys.stderr.write(
                    #    f"DEBUG '{cut_lineage}' count {culled} --> {more_cut} which is now {local_mito[more_cut]}\n"
                    # )
        assert sum(local_mito.values()) == total, "Oops - culling changed the total"
        if "" in local_mito and local_mito[""] < min_refs:
            # Cull this despite the total dropping
            del local_mito[""]
    sys.stderr.write(
        f"Reporting on {sum(local_mito.values())} mtDNA under {len(local_mito)} lineages under {root}\n"
    )
    # sort the dict:
    local_mito = dict(sorted(local_mito.items()))

    # TODO - Use defaultdict?
    for cut_lineage in local_mito:
        for primer_name in primer_defs:
            local_lengths[cut_lineage, primer_name] = []

    for lineage in mito_counts:
        cut_lineage = truncations[lineage]  # drop species, maybe also clumping
        while cut_lineage in truncations:
            cut_lineage = truncations[cut_lineage]  # culled using min_refs
        if not cut_lineage and cut_lineage not in local_mito:
            # Dropped "" (others under root) as too rare
            continue
        assert cut_lineage in local_mito, f"{lineage} -> {cut_lineage}"
        for primer_name in primer_defs:
            v = primer_counts[lineage, primer_name]  # int, can be zero
            assert isinstance(v, int), v
            if v:
                local_lengths[cut_lineage, primer_name].append(v)
    for cut_lineage in local_mito:
        for primer_name in primer_defs:
            assert (
                len(local_lengths[cut_lineage, primer_name]) <= local_mito[cut_lineage]
            ), f"{cut_lineage} {primer_name}: {len(local_lengths[cut_lineage, primer_name])} products from {local_mito[cut_lineage]} mtDNA for {cut_lineage if cut_lineage else 'Other ' + root}"

    # assert set(local_mito) == set(local_lengths)
    # print(f"{len(local_lengths)} entries for {root} level {levels}")
    with open(count_tsv_filename, "w") as handle:
        handle.write(
            f"#Primer counts vs Group for {root}\tmtDNA\t"
            + "\t".join(primer_defs.keys())
            + "\n"
        )
        for cut_lineage in local_mito:
            handle.write(
                f"{cut_lineage if cut_lineage else 'Other ' + root}\t{local_mito[cut_lineage]}\t"
                + "\t".join(
                    str(len(local_lengths[cut_lineage, primer_name]))
                    for primer_name in primer_defs
                )
                + "\n"
            )
    with open(median_tsv_filename, "w") as handle:
        handle.write(
            f"#Primer median length vs Group for {root}\tmtDNA\t"
            + "\t".join(primer_defs.keys())
            + "\n"
        )
        for cut_lineage in local_mito:
            handle.write(
                f"{cut_lineage if cut_lineage else 'Other ' + root}\t{local_mito[cut_lineage]}\t"
                + "\t".join(
                    str(median(local_lengths[cut_lineage, primer_name]))
                    if local_lengths[cut_lineage, primer_name]
                    else "-"
                    for primer_name in primer_defs
                )
                + "\n"
            )

    if plot:
        import pandas as pd
        import seaborn as sns
        from matplotlib.patches import Patch

        # color_map = sns.color_palette("Blues", as_cmap=True)
        # color_map = sns.cubehelix_palette(start=.5, rot=-.5, as_cmap=True)
        # color_map = sns.cubehelix_palette(start=2, as_cmap=True)  #dark green
        color_map = sns.cubehelix_palette(
            start=2.8, rot=0.1, light=0.9, as_cmap=True
        )  # blue/purple

        targets = sorted(set(primer_targets.values()))
        if targets:
            t_colors = sns.color_palette("Set1", len(targets))
            target_colors = [
                t_colors[targets.index(primer_targets[primer_name])]
                if primer_name in primer_targets
                else "white"
                for primer_name in primer_defs
            ]
            target_patches = [
                Patch(color=color, label=label)
                for color, label in zip(t_colors, targets)
            ]
        else:
            target_colors = None
            target_patches = None

        # Using dataframe as simple way to keep the row/col captions
        # matched up after clustering. Using mask for zero values
        # (thus background colour) for visual jump to small non-zero
        data_frame = pd.DataFrame(
            [
                [
                    100
                    * len(local_lengths[cut_lineage, primer_name])
                    / local_mito[cut_lineage]
                    for primer_name in primer_defs
                ]
                for cut_lineage in local_mito
            ],
            index=[
                f"{k if k else 'Other ' + root} ×{local_mito[k]}" for k in local_mito
            ],
            columns=primer_defs,
        )
        cluster_plot = sns.clustermap(
            data_frame,
            mask=(data_frame == 0),
            col_cluster=True,
            row_cluster=False,
            dendrogram_ratio=(0, 0.15),
            xticklabels=True,
            yticklabels=True,
            cmap=color_map,
            col_colors=target_colors,
            vmin=0,
            vmax=100,
            cbar_kws={
                "label": "Amplified",
                "format": "%.0f%%",
                "orientation": "horizontal",
            },
        )
        del data_frame

        # Bounding boxes are (x-min, y-min, x-max, y-max)
        heatmap_box = cluster_plot.ax_heatmap.get_position()
        # Set position is (x, y, width, height)
        cluster_plot.ax_cbar.set_position(
            (
                heatmap_box.xmax + 0.04,
                heatmap_box.ymin - 0.06,
                0.15,
                0.03,
            )
        )

        target_legend = cluster_plot.ax_heatmap.legend(
            loc="lower left",
            bbox_to_anchor=(1.03, 1.03),
            handles=target_patches,
            frameon=False,
        )
        target_legend.set_title(title="Primer target", prop={"size": 10})

        cluster_plot.savefig(plot)

    if workbook:
        worksheet = workbook.add_worksheet(root)
        worksheet.set_column(0, 0, 43)  # column width
        worksheet.set_column(1, 1, 6.5)
        worksheet.set_column(2, 2 + len(primer_defs), 8)
        worksheet.write_string(0, 0, f"Primer vs Group for {root}", header_fmt)
        worksheet.write_string(0, 1, "mtDNA", header_fmt)
        for j, name in enumerate(primer_defs):
            worksheet.write_string(0, 2 + j, name, word_wrap_fmt)
        for i, cut_lineage in enumerate(local_mito):
            worksheet.write_string(
                1 + i,
                0,
                cut_lineage.replace(";", "; ") if cut_lineage else "Other " + root,
            )
            worksheet.write_number(1 + i, 1, local_mito[cut_lineage])
            for j, primer_name in enumerate(primer_defs):
                # When an mtDNA amplified more than once, only kept
                # the shortest, so can just take len here:
                worksheet.write_number(
                    1 + i, 2 + j, len(local_lengths[cut_lineage, primer_name])
                )
                assert (
                    len(local_lengths[cut_lineage, primer_name])
                    <= local_mito[cut_lineage]
                ), f"{cut_lineage} {primer_name}: {len(local_lengths[cut_lineage, primer_name])} products from {local_mito[cut_lineage]} mtDNA for {cut_lineage if cut_lineage else 'Other'}"
        worksheet = workbook.add_worksheet(f"{root} - Percent")
        worksheet.set_column(0, 0, 43)  # column width
        worksheet.set_column(1, 1, 6.5)
        worksheet.set_column(2, 2 + len(primer_defs), 8)
        worksheet.write_string(0, 0, f"Primer vs Group for {root}", header_fmt)
        worksheet.write_string(0, 1, "mtDNA", header_fmt)
        for j, name in enumerate(primer_defs):
            worksheet.write_string(0, 2 + j, name, word_wrap_fmt)
        for i, cut_lineage in enumerate(local_mito):
            worksheet.write_string(
                1 + i,
                0,
                cut_lineage.replace(";", "; ") if cut_lineage else "Other " + root,
            )
            worksheet.write_number(1 + i, 1, local_mito[cut_lineage])
            for j, primer_name in enumerate(primer_defs):
                # When an mtDNA amplified more than once, only kept
                # the shorted, so can just take len here:
                worksheet.write_formula(
                    1 + i,
                    2 + j,
                    f"={root}!{xl_rowcol_to_cell(1 + i, 2 + j)}/{xl_rowcol_to_cell(1 + i, 1, True)}",
                    percent_fmt,
                    len(local_lengths[cut_lineage, primer_name])
                    / local_mito[cut_lineage],
                )
        worksheet.conditional_format(
            1, 2, 1 + len(local_lengths), 2 + len(primer_defs), percent_color_fmt
        )

        worksheet = workbook.add_worksheet(root + " - length median")
        worksheet.set_column(0, 0, 43)  # column width
        worksheet.set_column(1, 1, 6.5)
        worksheet.set_column(2, 2 + len(primer_defs), 8)
        worksheet.write_string(0, 0, f"Primer vs Group for {root}", header_fmt)
        worksheet.write_string(0, 1, "mtDNA", header_fmt)
        for j, name in enumerate(primer_defs):
            worksheet.write_string(0, 2 + j, name, word_wrap_fmt)
        for i, cut_lineage in enumerate(local_mito):
            worksheet.write_string(
                1 + i,
                0,
                cut_lineage.replace(";", "; ") if cut_lineage else "Other " + root,
            )
            worksheet.write_number(1 + i, 1, local_mito[cut_lineage])
            for j, primer_name in enumerate(primer_defs):
                if local_lengths[cut_lineage, primer_name]:
                    worksheet.write_number(
                        1 + i, 2 + j, median(local_lengths[cut_lineage, primer_name])
                    )
                else:
                    worksheet.write_string(1 + i, 2 + j, "-")

        worksheet = workbook.add_worksheet(root + " - length range")
        worksheet.set_column(0, 0, 43)  # column width
        worksheet.set_column(1, 1, 6.5)
        worksheet.set_column(2, 2 + len(primer_defs), 8)
        worksheet.write_string(0, 0, f"Primer vs Group for {root}", header_fmt)
        worksheet.write_string(0, 1, "mtDNA", header_fmt)
        for j, name in enumerate(primer_defs):
            worksheet.write_string(0, 2 + j, name, word_wrap_fmt)
        for i, cut_lineage in enumerate(local_mito):
            worksheet.write_string(
                1 + i,
                0,
                cut_lineage.replace(";", "; ") if cut_lineage else "Other " + root,
            )
            worksheet.write_number(1 + i, 1, local_mito[cut_lineage])
            for j, primer_name in enumerate(primer_defs):
                values = set(local_lengths[cut_lineage, primer_name])
                if len(values) == 1:
                    worksheet.write_string(1 + i, 2 + j, f"{min(values)} only")
                elif values:
                    worksheet.write_string(1 + i, 2 + j, f"{min(values)}-{max(values)}")
                else:
                    worksheet.write_string(1 + i, 2 + j, "-")


if args.excel:
    import xlsxwriter
    from xlsxwriter.utility import xl_rowcol_to_cell

    workbook = xlsxwriter.Workbook(excel_file)
    workbook.formats[0].set_font_size(12)  # change default
    workbook.formats[0].set_font_name("Arial")
    workbook.formats[0].set_border(BORDER_STYLE)
    workbook.formats[0].set_border_color(BORDER_COLOR)

    # Header row is bold white text on RGB 120,0,79 with 0.5pt black lines
    # First column is also bold.
    # Font indent is left 0.15cm
    header_fmt = workbook.add_format(
        {
            "font_name": "Arial",
            "font_size": 12,
            "border": BORDER_STYLE,
            "border_color": BORDER_COLOR,
            "bg_color": "#78004F",
            "font_color": "white",
            "bold": True,
        }
    )
    word_wrap_fmt = workbook.add_format(
        {
            "font_name": "Arial",
            "font_size": 12,
            "border": BORDER_STYLE,
            "border_color": BORDER_COLOR,
            "bg_color": "#78004F",
            "font_color": "white",
            "bold": True,
            "text_wrap": True,
        }
    )

    percent_fmt = workbook.add_format(
        {
            "num_format": "0.0%",
            "font_name": "Arial",
            "font_size": 12,
            "border": BORDER_STYLE,
            "border_color": BORDER_COLOR,
        }
    )
    percent_color_fmt = {
        "type": "3_color_scale",
        "min_color": "white",  # default red
        "min_type": "num",
        "min_value": 0,
        "mid_type": "num",
        "mid_value": 0.5,
        "max_type": "num",
        "max_value": 1,
    }
    percent_color_fmt = {
        "type": "2_color_scale",
        "min_color": "white",
        "min_type": "num",
        "min_value": 0,
        "max_color": "#909090",
        "max_type": "num",
        "max_value": 1,
    }
else:
    workbook = None

report_group(
    f"{args.output}_counts.tsv",
    f"{args.output}_median.tsv",
    workbook,
    args.root,
    args.levels,
    args.clump,
    plot=f"{args.output}_fraction.pdf" if args.plot else None,
    min_refs=args.min_refs,
)
if workbook:
    workbook.close()
