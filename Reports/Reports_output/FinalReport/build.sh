#!/bin/sh
# Build the combined final report.
# Usage:  ./build.sh      (run from anywhere; it cd's to its own folder)
#
# Edit FinalReport.tex or chapters/*.tex, then run this to refresh BOTH PDFs.

set -e
cd "$(dirname "$0")"

# Three passes. Two are enough only when FinalReport.aux/.toc already exist from
# an earlier build. On a fresh clone they do not, and the run goes 32 pages (no
# contents yet) -> 33 pages (contents inserted), so a second pass still prints the
# page numbers measured during the first. The third pass is what makes a clean
# checkout produce byte-for-byte the same PDF as an incremental build.
pdflatex -interaction=nonstopmode -halt-on-error FinalReport.tex
pdflatex -interaction=nonstopmode -halt-on-error FinalReport.tex
pdflatex -interaction=nonstopmode -halt-on-error FinalReport.tex

# Keep the convenience copy in the parent folder in sync.
cp FinalReport.pdf ../GTM_Agent_Final_Report.pdf

# Remove only cosmetic clutter. KEEP FinalReport.aux and FinalReport.toc so the
# table of contents and cross-references always resolve on the next build.
rm -f FinalReport.log FinalReport.out

echo ""
echo "Done. Updated:"
echo "  - FinalReport/FinalReport.pdf"
echo "  - GTM_Agent_Final_Report.pdf"
