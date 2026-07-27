#!/bin/sh
# Build the combined final report.
# Usage:  ./build.sh      (run from anywhere; it cd's to its own folder)
#
# Edit FinalReport.tex or chapters/*.tex, then run this to refresh BOTH PDFs.

set -e
cd "$(dirname "$0")"

# Two passes so the table of contents and page numbers resolve correctly.
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
